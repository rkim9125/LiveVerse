// Pure helpers for the interpreter screen: what to show, given server state.
// No DOM here, so they can be tested in Node.

export const SOURCE_LABEL = {
  rule: "said",
  context: "context",
  quote: "quote",
  llm: "guess",
  manual: "manual",
  reading: "reading",
};

export const FONT_MIN = 14;
export const FONT_MAX = 40;
export const FONT_STEP = 2;

export function clampFont(size, delta = 0) {
  return Math.min(FONT_MAX, Math.max(FONT_MIN, size + delta));
}

function verseOf(ref) {
  // "jo 3:16" -> {book, chapter, verse}; "jo 3" -> verse null
  const m = /^(\S+) (\d+)(?::(\d+))?/.exec(ref ?? "");
  return m ? { book: m[1], chapter: Number(m[2]), verse: m[3] ? Number(m[3]) : null } : null;
}

/** The main passage: title, marks and verse rows (Korean and English side by side). */
export function passageView(shown, reading = null) {
  if (!shown) return null;
  const marks = [];
  if (shown.interim) marks.push({ kind: "interim", text: "interim" });
  if (shown.tentative) marks.push({ kind: "tentative", text: "tentative" });
  if (shown.manual) marks.push({ kind: "manual", text: "manual" });
  const read = verseOf(reading?.ref);
  const here = verseOf(shown.ref);
  const sameChapter = read && here && read.book === here.book && read.chapter === here.chapter;
  const verses = shown.verses ?? [];
  return {
    hasKo: verses.some((v) => v.ko),
    hasEn: verses.some((v) => v.en),
    ko: shown.label?.ko ?? shown.ref,
    en: shown.label?.en ?? "",
    source: shown.manual ? "manual" : shown.source,
    sourceLabel: SOURCE_LABEL[shown.manual ? "manual" : shown.source] ?? shown.source,
    confidence: shown.confidence,
    marks,
    interim: Boolean(shown.interim),
    rows: verses.map((v) => ({
      num: v.num,
      ko: v.ko ?? "",
      en: v.en ?? "",
      reading: Boolean(sameChapter && read.verse === v.num),
    })),
  };
}

/** Up to three alternatives, numbered for the 1 to 3 keys. */
export function alternativesView(alternatives = []) {
  return alternatives.slice(0, 3).map((a, i) => ({
    key: String(i + 1),
    id: a.id,
    text: a.label?.ko ? `${a.label.ko} · ${a.label.en}` : a.ref,
    source: SOURCE_LABEL[a.source] ?? a.source,
    confidence: a.confidence,
    faint: Boolean(a.dimmed || a.guess),
    guess: Boolean(a.guess),
  }));
}

export function spokenView(spoken) {
  if (!spoken) return "";
  if (spoken.ref) return spoken.ref;
  return spoken.book ? `${spoken.book} (chapter unknown)` : "";
}

/**
 * Speech status for the header.
 * connected: WebSocket up. activity: /api/stt reply. listening: this page's own
 * Web Speech status, or null when this page is not listening.
 */
export function sttStatus({ connected, activity, listening }) {
  if (!connected) return { level: "error", text: "server offline" };
  if (listening && listening.error) return { level: "error", text: `mic: ${listening.error}` };
  if (!activity || (activity.last_final == null && activity.last_interim == null)) {
    return { level: "idle", text: listening?.running ? "listening, no speech yet" : "no speech input" };
  }
  const last = Math.max(...[activity.last_final, activity.last_interim].filter((t) => t != null));
  const age = Math.max(0, activity.now - last);
  if (age < 5) return { level: "ok", text: "hearing speech" };
  if (age < 60) return { level: "warn", text: `quiet ${Math.round(age)} s` };
  return { level: "idle", text: `quiet ${Math.round(age / 60)} min` };
}

/** Keyboard shortcuts. Returns an action, or null. Typing in a field is left alone. */
export function keyAction(key, { inField = false, ctrl = false, meta = false } = {}) {
  if (inField) return key === "Escape" ? { type: "blur" } : null;
  if (ctrl || meta) return null;
  if (key >= "1" && key <= "3") return { type: "switch", index: Number(key) - 1 };
  if (key === "Escape") return { type: "clear" };
  if (key === "/") return { type: "search" };
  if (key === "+" || key === "=") return { type: "font", delta: FONT_STEP };
  if (key === "-" || key === "_") return { type: "font", delta: -FONT_STEP };
  if (key === "t" || key === "T") return { type: "theme" };
  if (key === "l" || key === "L") return { type: "listen" };
  if (key === "?") return { type: "help" };
  return null;
}
