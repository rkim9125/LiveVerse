import { Capture } from "../shared/capture.js";
import { WebSpeechSource, speechSupported } from "../shared/speech.js";
import { LiveVerseSocket } from "../shared/ws.js";

const $ = (id) => document.getElementById(id);
const wsUrl = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`;

let nextSeq = 1;
let finals = 0;
let capture = null;
const finalSentAt = new Map(); // seq -> ms when the final was sent

function setMessage(text, level = "") {
  const el = $("message");
  el.textContent = text;
  el.className = level ? `status-${level}` : "";
}

// ── server ──

const socket = new LiveVerseSocket(wsUrl, {
  onStatus: ({ connected }) => {
    $("conn").textContent = connected ? "connected" : "reconnecting";
  },
  onError: (message) => setMessage(message, "error"),
  onPreview: () => {},
  onState: (state) => {
    renderState(state);
    requestAnimationFrame(() => {
      socket.rendered(state.seq);
      const sent = finalSentAt.get(state.seq);
      if (sent) {
        const received = state.t_sent * 1000;
        $("latency").textContent =
          `final → screen ${Math.round(performance.timeOrigin + performance.now() - sent)} ms ` +
          `(server ${Math.round((state.t_sent - state.t_recv) * 1000)} ms, ` +
          `then ${Math.round(performance.timeOrigin + performance.now() - received)} ms)`;
        finalSentAt.delete(state.seq);
      }
    });
  },
});
socket.connect();

function renderState(state) {
  const shown = state.shown;
  if (!shown) {
    $("shown-ref").textContent = "nothing shown";
    $("shown-source").hidden = true;
    $("shown-confidence").textContent = "";
    $("verses").textContent = "";
  } else {
    $("shown-ref").textContent = `${shown.label.ko} · ${shown.label.en}`;
    $("shown-source").hidden = false;
    $("shown-source").textContent = shown.manual ? "manual" : shown.source;
    $("shown-confidence").textContent = `confidence ${shown.confidence}${shown.tentative ? " (tentative)" : ""}`;
    const first = shown.verses[0];
    $("verses").textContent = first
      ? `${first.num} ${first.en || first.ko}${shown.verses.length > 1 ? ` … (${shown.verses.length} verses)` : ""}`
      : "";
  }
  const list = $("alternatives");
  list.replaceChildren(
    ...state.alternatives.map((alt) => {
      const li = document.createElement("li");
      const button = document.createElement("button");
      const guess = alt.guess ? " · guess" : "";
      button.textContent = `${alt.ref} · ${alt.source} · ${alt.confidence}${guess}`;
      if (alt.dimmed || alt.guess) button.className = "dimmed";
      button.addEventListener("click", () => socket.send({ type: "switch", candidate_id: alt.id }));
      li.append(button);
      return li;
    }),
  );
}

$("search-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const query = $("search").value.trim();
  if (query) socket.send({ type: "search", query });
});
$("clear").addEventListener("click", () => socket.send({ type: "clear" }));

// ── speech ──

let source = null;

function onSegment(seg) {
  const seq = nextSeq;
  socket.sendTranscript({ seq, text: seg.text, isFinal: seg.isFinal, tEnd: seg.tEnd });
  if (!seg.isFinal) {
    $("interim").textContent = seg.text;
    return;
  }
  finalSentAt.set(seq, Date.now());
  nextSeq += 1;
  finals += 1;
  $("final-count").textContent = String(finals);
  $("interim").textContent = "";
  const li = document.createElement("li");
  li.textContent = seg.text;
  $("finals").prepend(li);
  while ($("finals").children.length > 10) $("finals").lastChild.remove();
  if (capture) capture.add(seg);
}

function onStatus(status) {
  $("speech-state").textContent = status.running ? "listening" : "stopped";
  $("restarts").textContent = String(status.restarts);
  $("gaps").textContent = `${(status.gapMs / 1000).toFixed(1)} s`;
  const bad = ["not-allowed", "service-not-allowed", "audio-capture"].includes(status.lastError);
  if (status.message) setMessage(status.message, bad ? "error" : status.lastError === "network" ? "warn" : "");
  if (!status.running) {
    $("start").disabled = false;
    $("stop").disabled = true;
  }
}

async function showInputDevice() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const track = stream.getAudioTracks()[0];
    $("device").textContent = track ? track.label : "none";
    stream.getTracks().forEach((t) => t.stop());
  } catch (err) {
    $("device").textContent = "permission needed";
    setMessage(`Microphone: ${err.message}`, "error");
  }
}

$("start").addEventListener("click", async () => {
  if (!speechSupported()) {
    setMessage("This browser has no Web Speech API. Use Chrome.", "error");
    return;
  }
  await showInputDevice();
  if ($("eval-mode").checked) {
    capture = new Capture();
    $("save").disabled = false;
  }
  source = new WebSpeechSource({ lang: "ko-KR", onSegment, onStatus });
  source.start();
  $("start").disabled = true;
  $("stop").disabled = false;
  $("eval-mode").disabled = true;
});

$("stop").addEventListener("click", () => {
  if (source) source.stop();
  $("eval-mode").disabled = false;
});

$("save").addEventListener("click", () => {
  if (!capture) return;
  const stats = source ? { restarts: source.restarts, gap_ms: source.gapMs, finals } : { finals };
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  capture.download(`webspeech-capture-${stamp}.json`, stats);
  setMessage("Transcript saved to Downloads. Move it into the corpus folder (see docs).");
});
