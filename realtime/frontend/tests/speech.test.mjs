// Run: node --test realtime/frontend/tests/
import assert from "node:assert/strict";
import { test } from "node:test";

import { Capture } from "../shared/capture.js";
import { WebSpeechSource, speechSupported } from "../shared/speech.js";
import { LiveVerseSocket } from "../shared/ws.js";

// ── fakes ──

class FakeRecognition {
  static instances = [];
  constructor() {
    FakeRecognition.instances.push(this);
    this.started = 0;
    this.stopped = 0;
  }
  start() {
    this.started += 1;
    this.onstart?.();
  }
  stop() {
    this.stopped += 1;
    this.onend?.();
  }
}

function results(list, resultIndex = 0) {
  // list: [[text, isFinal], ...]
  const res = list.map(([text, isFinal]) => Object.assign([{ transcript: text }], { isFinal }));
  return { resultIndex, results: res };
}

function makeSource(extra = {}) {
  FakeRecognition.instances = [];
  let t = 1000;
  const timers = [];
  const segments = [];
  const statuses = [];
  const src = new WebSpeechSource({
    Recognition: FakeRecognition,
    now: () => t,
    setTimer: (fn, ms) => timers.push({ fn, ms }),
    onSegment: (s) => segments.push(s),
    onStatus: (s) => statuses.push(s),
    ...extra,
  });
  return {
    src,
    segments,
    statuses,
    timers,
    advance: (ms) => (t += ms),
    rec: () => FakeRecognition.instances.at(-1),
  };
}

// ── speech ──

test("support check", () => {
  assert.equal(speechSupported({}), false);
  assert.equal(speechSupported({ webkitSpeechRecognition: FakeRecognition }), true);
});

test("configures Korean continuous recognition with interim results", () => {
  const h = makeSource();
  h.src.start();
  const rec = h.rec();
  assert.equal(rec.lang, "ko-KR");
  assert.equal(rec.continuous, true);
  assert.equal(rec.interimResults, true);
});

test("interim then final carry the first interim time as start", () => {
  const h = makeSource();
  h.src.start();
  h.rec().onresult(results([["요한복음", false]]));
  h.advance(400);
  h.rec().onresult(results([["요한복음 3장", false]]));
  h.advance(900);
  h.rec().onresult(results([["요한복음 3장 16절", true]]));
  assert.deepEqual(
    h.segments.map((s) => [s.text, s.isFinal, s.tStart, s.tEnd]),
    [
      ["요한복음", false, 1000, 1000],
      ["요한복음 3장", false, 1000, 1400],
      ["요한복음 3장 16절", true, 1000, 2300],
    ],
  );
});

test("interim results are throttled, finals never are", () => {
  const h = makeSource();
  h.src.start();
  h.rec().onresult(results([["a", false]]));
  h.advance(100);
  h.rec().onresult(results([["ab", false]]));
  h.advance(100);
  h.rec().onresult(results([["abc", true]]));
  assert.deepEqual(h.segments.map((s) => s.text), ["a", "abc"]);
});

test("automatic restart when recognition ends, gap is measured", () => {
  const h = makeSource();
  h.src.start();
  h.rec().onend();
  assert.equal(h.src.restarts, 1);
  assert.equal(h.timers.at(-1).ms, 0);
  h.advance(250);
  h.timers.at(-1).fn();
  assert.equal(FakeRecognition.instances.length, 2);
  assert.equal(h.src.gapMs, 250);
});

test("stop does not restart", () => {
  const h = makeSource();
  h.src.start();
  h.src.stop();
  assert.equal(h.src.restarts, 0);
  assert.equal(h.timers.length, 0);
});

test("network errors back off 1, 2, 4 seconds", () => {
  const h = makeSource();
  h.src.start();
  for (const want of [1000, 2000, 4000, 4000]) {
    h.rec().onerror({ error: "network" });
    h.rec().onend();
    assert.equal(h.timers.at(-1).ms, want);
    h.timers.at(-1).fn();
  }
  h.rec().onresult(results([["ok", true]]));
  h.rec().onend();
  assert.equal(h.timers.at(-1).ms, 0); // a result resets the backoff
});

test("permission denied and missing microphone stop listening", () => {
  for (const error of ["not-allowed", "service-not-allowed", "audio-capture"]) {
    const h = makeSource();
    h.src.start();
    h.rec().onerror({ error });
    h.rec().onend();
    assert.equal(h.src.running, false, error);
    assert.equal(h.timers.length, 0, error);
    assert.match(h.statuses.at(-1).message, /permission|microphone/);
  }
});

test("no-speech keeps listening", () => {
  const h = makeSource();
  h.src.start();
  h.rec().onerror({ error: "no-speech" });
  h.rec().onend();
  assert.equal(h.src.running, true);
  assert.equal(h.src.restarts, 1);
});

test("throws without Web Speech", () => {
  assert.throws(() => new WebSpeechSource({ Recognition: undefined }), /not available/);
});

// ── capture ──

test("capture keeps finals in seconds", () => {
  const c = new Capture({ now: () => 5000 });
  c.add({ text: "x", isFinal: false, tStart: 1000, tEnd: 1500 });
  c.add({ text: "요한복음 3장 16절", isFinal: true, tStart: 2000, tEnd: 3500 });
  const out = c.toJSON({ restarts: 2 });
  assert.equal(out.time_base, "epoch_seconds");
  assert.deepEqual(out.segments, [{ start: 2, end: 3.5, text: "요한복음 3장 16절" }]);
  assert.deepEqual(out.stats, { restarts: 2 });
});

// ── socket ──

class FakeSocket {
  static last = null;
  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.sent = [];
    FakeSocket.last = this;
  }
  open() {
    this.readyState = 1;
    this.onopen();
  }
  send(data) {
    this.sent.push(JSON.parse(data));
  }
  close() {
    this.readyState = 3;
    this.onclose();
  }
}

function makeSocket() {
  const timers = [];
  const got = { state: [], preview: [], errors: [], status: [] };
  const sock = new LiveVerseSocket("ws://127.0.0.1:8000/ws", {
    WebSocketImpl: FakeSocket,
    now: () => 10_000,
    setTimer: (fn, ms) => timers.push({ fn, ms }),
    onState: (m) => got.state.push(m),
    onPreview: (m) => got.preview.push(m),
    onError: (m) => got.errors.push(m),
    onStatus: (s) => got.status.push(s),
  });
  return { sock, timers, got };
}

test("pings on open and sends transcripts in the protocol shape", () => {
  const { sock } = makeSocket();
  sock.connect();
  FakeSocket.last.open();
  assert.equal(FakeSocket.last.sent.filter((m) => m.type === "ping").length, 5);
  sock.sendTranscript({ seq: 3, text: "17절", isFinal: true, tEnd: 12_500, tAudio: 61.5 });
  assert.deepEqual(FakeSocket.last.sent.at(-1), {
    type: "transcript", seq: 3, text: "17절", is_final: true, lang: "ko-KR", t_client: 12.5, t_audio: 61.5,
  });
});

test("dispatches state, preview and error messages", () => {
  const { sock, got } = makeSocket();
  sock.connect();
  FakeSocket.last.open();
  FakeSocket.last.onmessage({ data: JSON.stringify({ type: "state", seq: 1 }) });
  FakeSocket.last.onmessage({ data: JSON.stringify({ type: "preview", seq: 2 }) });
  FakeSocket.last.onmessage({ data: JSON.stringify({ type: "error", message: "bad" }) });
  FakeSocket.last.onmessage({ data: "not json" });
  assert.equal(got.state.length, 1);
  assert.equal(got.preview.length, 1);
  assert.deepEqual(got.errors, ["bad"]);
});

test("reconnects with backoff and resends finals kept while offline", () => {
  const { sock, timers } = makeSocket();
  sock.connect();
  const first = FakeSocket.last;
  first.open();
  first.close();
  assert.equal(timers.at(-1).ms, 1000);
  sock.sendTranscript({ seq: 9, text: "다음 절", isFinal: true, tEnd: 1 });
  sock.sendTranscript({ seq: 9, text: "다음", isFinal: false, tEnd: 1 }); // interim is dropped
  timers.at(-1).fn();
  FakeSocket.last.open();
  const transcripts = FakeSocket.last.sent.filter((m) => m.type === "transcript");
  assert.deepEqual(transcripts.map((m) => m.text), ["다음 절"]);
});

test("rendered reports the screen time", () => {
  const { sock } = makeSocket();
  sock.connect();
  FakeSocket.last.open();
  sock.rendered(4);
  assert.deepEqual(FakeSocket.last.sent.at(-1), { type: "rendered", seq: 4, t_render: 10 });
  sock.close();
});
