// Interpreter screen: the passage the preacher is on, large, Korean and English
// side by side. State comes from the server over /ws; speech can come from this
// page (Web Speech, the Listen button) or from another source such as the
// Whisper worker.

import { WebSpeechSource, speechSupported } from "../shared/speech.js";
import { LiveVerseSocket } from "../shared/ws.js";
import {
  alternativesView,
  clampFont,
  keyAction,
  passageView,
  spokenView,
  sttStatus,
} from "./view.js";

const $ = (id) => document.getElementById(id);
const wsUrl = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`;

// ── preferences (per browser; the page works without storage) ──

function load(key, fallback) {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}
function save(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* private window or blocked storage */
  }
}

let fontSize = clampFont(Number(load("lv.font", 22)) || 22);
function applyFont() {
  document.documentElement.style.setProperty("--verse-size", `${fontSize}px`);
}
function applyTheme(theme) {
  if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
}
applyFont();
applyTheme(load("lv.theme", ""));

function toggleTheme() {
  const dark =
    document.documentElement.dataset.theme === "dark" ||
    (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
  const next = dark ? "light" : "dark";
  applyTheme(next);
  save("lv.theme", next);
}

// ── rendering ──

let state = null;
let connected = false;
let activity = null;
let listening = null; // this page's Web Speech status, or null

function el(tag, attrs = {}, text = "") {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text) node.textContent = text;
  return node;
}

function renderPassage() {
  const view = passageView(state?.shown, state?.reading);
  $("empty").hidden = Boolean(view);
  $("shown").hidden = !view;
  $("passage").classList.toggle("interim", Boolean(view?.interim));
  if (!view) return;
  $("title-ko").textContent = view.ko;
  $("title-en").textContent = view.en;
  const marks = [el("span", { class: "pill source" }, view.sourceLabel)];
  if (view.confidence != null && view.source !== "manual") marks.push(el("span", { class: "pill" }, `${Math.round(view.confidence * 100)}%`));
  for (const m of view.marks) {
    if (m.kind !== "manual") marks.push(el("span", { class: `pill ${m.kind}` }, m.text));
  }
  $("marks").replaceChildren(...marks);
  const both = view.hasKo && view.hasEn;
  $("verses").className = both ? "" : view.hasKo ? "only-ko" : "only-en";
  const head = [];
  if (both && state.names) {
    const row = el("div", { class: "row head", role: "row" });
    row.append(
      el("span", { class: "num", role: "columnheader" }, ""),
      el("span", { class: "ko", role: "columnheader" }, state.names.ko ?? ""),
      el("span", { class: "en", role: "columnheader" }, state.names.en ?? ""),
    );
    head.push(row);
  }
  $("verses").replaceChildren(
    ...head,
    ...view.rows.map((r) => {
      const row = el("div", { class: r.reading ? "row reading" : "row", role: "row", "data-verse": String(r.num) });
      row.append(
        el("span", { class: "num", role: "cell" }, String(r.num)),
        el("span", { class: "ko", role: "cell", lang: "ko" }, r.ko),
        el("span", { class: "en", role: "cell", lang: "en" }, r.en),
      );
      return row;
    }),
  );
}

function renderSide() {
  const alts = alternativesView(state?.alternatives);
  $("no-alternatives").hidden = alts.length > 0;
  $("alternatives").replaceChildren(
    ...alts.map((a) => {
      const button = el("button", { type: "button", "data-id": a.id });
      if (a.faint) button.classList.add("faint");
      button.append(
        el("kbd", {}, a.key),
        el("span", {}, a.text),
        el("span", { class: "meta" }, `${a.guess ? "guess" : a.source} ${Math.round(a.confidence * 100)}%`),
      );
      button.addEventListener("click", () => socket.send({ type: "switch", candidate_id: a.id }));
      const li = el("li");
      li.append(button);
      return li;
    }),
  );
  $("spoken").textContent = spokenView(state?.spoken) || "unknown";
  $("reading").textContent = state?.reading ? `reading ${state.reading.ref}` : "";
}

function renderStatus() {
  $("conn").textContent = connected ? "connected" : "reconnecting";
  $("conn-dot").className = `dot ${connected ? "ok" : "error"}`;
  const s = sttStatus({ connected, activity, listening });
  $("stt").textContent = s.text;
  $("stt-dot").className = `dot ${s.level}`;
  $("listen").setAttribute("aria-pressed", String(Boolean(listening?.running)));
}

function setMessage(text) {
  $("message").textContent = text;
}

// ── server ──

const socket = new LiveVerseSocket(wsUrl, {
  onStatus: ({ connected: up }) => {
    connected = up;
    renderStatus();
  },
  onError: (message) => setMessage(message),
  onState: (msg) => {
    state = msg;
    setMessage("");
    renderPassage();
    renderSide();
    requestAnimationFrame(() => socket.rendered(msg.seq, Boolean(msg.from_interim)));
  },
});
socket.connect();

async function pollActivity() {
  try {
    const res = await fetch("/api/stt", { cache: "no-store" });
    if (res.ok) activity = await res.json();
  } catch {
    activity = null;
  }
  renderStatus();
}
pollActivity();
setInterval(pollActivity, 2000);

// ── this page as a speech source (optional) ──

let source = null;
let nextSeq = 1;

function toggleListen() {
  if (source) {
    source.stop();
    source = null;
    listening = null;
    renderStatus();
    return;
  }
  if (!speechSupported()) {
    setMessage("This browser has no Web Speech API. Use Chrome, or the Whisper worker.");
    return;
  }
  source = new WebSpeechSource({
    lang: "ko-KR",
    onSegment: (seg) => {
      socket.sendTranscript({ seq: nextSeq, text: seg.text, isFinal: seg.isFinal, tEnd: seg.tEnd });
      if (seg.isFinal) nextSeq += 1;
    },
    onStatus: (status) => {
      const bad = ["not-allowed", "service-not-allowed", "audio-capture"].includes(status.lastError);
      listening = { running: status.running, error: bad ? status.lastError : null };
      renderStatus();
    },
  });
  source.start();
  listening = { running: true, error: null };
  renderStatus();
}

// ── controls ──

$("search-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const query = $("search").value.trim();
  if (!query) return;
  socket.send({ type: "search", query });
  $("search").value = "";
  $("search").blur();
});
$("listen").addEventListener("click", toggleListen);
$("smaller").addEventListener("click", () => changeFont(-2));
$("larger").addEventListener("click", () => changeFont(2));
$("theme").addEventListener("click", toggleTheme);
$("help-open").addEventListener("click", () => $("help").classList.add("open"));
$("help").addEventListener("click", () => $("help").classList.remove("open"));

function changeFont(delta) {
  fontSize = clampFont(fontSize, delta);
  applyFont();
  save("lv.font", String(fontSize));
}

document.addEventListener("keydown", (e) => {
  const inField = e.target instanceof HTMLInputElement;
  const action = keyAction(e.key, { inField, ctrl: e.ctrlKey, meta: e.metaKey });
  if (!action) return;
  if ($("help").classList.contains("open") && action.type !== "help") {
    $("help").classList.remove("open");
    if (action.type === "clear") return e.preventDefault();
  }
  e.preventDefault();
  switch (action.type) {
    case "blur":
      e.target.blur();
      break;
    case "switch": {
      const alt = alternativesView(state?.alternatives)[action.index];
      if (alt) socket.send({ type: "switch", candidate_id: alt.id });
      break;
    }
    case "clear":
      socket.send({ type: "clear" });
      break;
    case "search":
      $("search").focus();
      break;
    case "font":
      changeFont(action.delta);
      break;
    case "theme":
      toggleTheme();
      break;
    case "listen":
      toggleListen();
      break;
    case "help":
      $("help").classList.toggle("open");
      break;
  }
});

renderPassage();
renderSide();
renderStatus();
