// Evaluation capture: keeps final segments with their wall-clock times so a
// recorded run can be scored later. The file is saved by the browser into the
// person's Downloads; it never goes to the server.

export class Capture {
  constructor({ source = "webspeech", lang = "ko-KR", now = () => Date.now() } = {}) {
    Object.assign(this, { source, lang, now });
    this.segments = [];
    this.startedAt = now();
  }

  add({ text, isFinal, tStart, tEnd }) {
    if (!isFinal) return;
    this.segments.push({ start: tStart / 1000, end: tEnd / 1000, text });
  }

  toJSON(stats = {}) {
    return {
      source: this.source,
      lang: this.lang,
      time_base: "epoch_seconds",
      started_at: this.startedAt / 1000,
      saved_at: this.now() / 1000,
      stats,
      segments: this.segments,
    };
  }

  download(filename, stats = {}, doc = globalThis.document) {
    const blob = new Blob([JSON.stringify(this.toJSON(stats), null, 1)], { type: "application/json" });
    const link = doc.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    link.click();
    URL.revokeObjectURL(link.href);
  }
}
