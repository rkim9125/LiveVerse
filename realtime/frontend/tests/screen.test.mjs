import assert from "node:assert/strict";
import { test } from "node:test";

import {
  FONT_MAX,
  FONT_MIN,
  alternativesView,
  clampFont,
  keyAction,
  passageView,
  spokenView,
  sttStatus,
} from "../screen/view.js";

const shown = {
  id: "c1",
  ref: "jo 3:16-17",
  label: { ko: "요한복음 3:16-17", en: "John 3:16-17" },
  source: "rule",
  confidence: 0.9,
  interim: false,
  tentative: false,
  manual: false,
  verses: [
    { num: 16, ko: "KO16", en: "EN16" },
    { num: 17, ko: "KO17", en: "EN17" },
  ],
};

test("passage view: titles, source and rows side by side", () => {
  const v = passageView(shown);
  assert.equal(v.ko, "요한복음 3:16-17");
  assert.equal(v.en, "John 3:16-17");
  assert.equal(v.sourceLabel, "said");
  assert.deepEqual(
    v.rows.map((r) => [r.num, r.ko, r.en, r.reading]),
    [
      [16, "KO16", "EN16", false],
      [17, "KO17", "EN17", false],
    ],
  );
  assert.equal(passageView(null), null);
});

test("passage view marks interim, tentative and manual", () => {
  const v = passageView({ ...shown, interim: true, tentative: true, manual: true });
  assert.ok(v.interim);
  assert.deepEqual(
    v.marks.map((m) => m.kind),
    ["interim", "tentative", "manual"],
  );
  assert.equal(v.sourceLabel, "manual");
});

test("reading highlights the verse being read in the same chapter only", () => {
  const v = passageView(shown, { ref: "jo 3:17", outcome: "reading", confidence: 0.8 });
  assert.deepEqual(
    v.rows.map((r) => r.reading),
    [false, true],
  );
  const other = passageView(shown, { ref: "jo 4:17" });
  assert.ok(other.rows.every((r) => !r.reading));
});

test("alternatives: at most three, numbered, guesses and dimmed are faint", () => {
  const alts = [
    { id: "a", ref: "rm 8:28", label: { ko: "로마서 8:28", en: "Romans 8:28" }, source: "rule", confidence: 0.9 },
    { id: "b", ref: "rm 7:1", source: "rule", confidence: 0.3, guess: true },
    { id: "c", ref: "jo 4", source: "rule", confidence: 0.75, dimmed: true },
    { id: "d", ref: "gn 1:1", source: "quote", confidence: 0.7 },
  ];
  const v = alternativesView(alts);
  assert.deepEqual(
    v.map((a) => [a.key, a.id, a.faint]),
    [
      ["1", "a", false],
      ["2", "b", true],
      ["3", "c", true],
    ],
  );
  assert.equal(v[0].text, "로마서 8:28 · Romans 8:28");
  assert.equal(v[1].text, "rm 7:1");
});

test("spoken position, including a book with no chapter", () => {
  assert.equal(spokenView({ ref: "jo 3:16" }), "jo 3:16");
  assert.equal(spokenView({ ref: null, book: "rm" }), "rm (chapter unknown)");
  assert.equal(spokenView(null), "");
});

test("speech status from the connection, activity and this page's mic", () => {
  assert.equal(sttStatus({ connected: false }).level, "error");
  assert.equal(sttStatus({ connected: true, activity: null }).text, "no speech input");
  const act = (age) => ({ now: 100, last_final: 100 - age, last_interim: null });
  assert.equal(sttStatus({ connected: true, activity: act(2) }).level, "ok");
  assert.equal(sttStatus({ connected: true, activity: act(20) }).text, "quiet 20 s");
  assert.equal(sttStatus({ connected: true, activity: act(300) }).text, "quiet 5 min");
  assert.equal(
    sttStatus({ connected: true, activity: act(2), listening: { running: false, error: "not-allowed" } }).level,
    "error",
  );
});

test("keyboard shortcuts, and typing in the search box is left alone", () => {
  assert.deepEqual(keyAction("2"), { type: "switch", index: 1 });
  assert.deepEqual(keyAction("Escape"), { type: "clear" });
  assert.deepEqual(keyAction("/"), { type: "search" });
  assert.equal(keyAction("+").type, "font");
  assert.equal(keyAction("t").type, "theme");
  assert.equal(keyAction("l").type, "listen");
  assert.equal(keyAction("4"), null);
  assert.equal(keyAction("2", { inField: true }), null);
  assert.deepEqual(keyAction("Escape", { inField: true }), { type: "blur" });
  assert.equal(keyAction("1", { meta: true }), null);
});

test("font size stays within bounds", () => {
  assert.equal(clampFont(FONT_MAX, 2), FONT_MAX);
  assert.equal(clampFont(FONT_MIN, -2), FONT_MIN);
  assert.equal(clampFont(22, 2), 24);
});
