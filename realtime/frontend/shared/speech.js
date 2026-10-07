// Speech sources for the interpreter screen.
//
// A SpeechSource turns audio into transcript segments:
//   start(), stop(), status()
//   onSegment({ text, isFinal, tStart, tEnd })   times in epoch milliseconds
//   onStatus({ running, restarts, gapMs, lastError, message })
//
// WebSpeechSource uses Chrome's Web Speech API. A later ServerAudioSource will
// stream microphone audio to the server (Whisper) behind the same interface,
// so pages do not change.

const RESTART_BACKOFF_MS = [1000, 2000, 4000];

export function speechSupported(globalObj = globalThis) {
  return Boolean(globalObj.SpeechRecognition || globalObj.webkitSpeechRecognition);
}

export class WebSpeechSource {
  constructor({
    lang = "ko-KR",
    Recognition = globalThis.SpeechRecognition || globalThis.webkitSpeechRecognition,
    now = () => Date.now(),
    setTimer = (fn, ms) => setTimeout(fn, ms),
    interimMs = 300,
    onSegment = () => {},
    onStatus = () => {},
  } = {}) {
    if (!Recognition) throw new Error("Web Speech API is not available in this browser");
    Object.assign(this, { lang, Recognition, now, setTimer, interimMs, onSegment, onStatus });
    this.running = false;
    this.restarts = 0;
    this.gapMs = 0;
    this.lastError = null;
    this._networkErrors = 0;
    this._gapStart = null;
    this._firstSeen = new Map(); // result index -> time of its first interim
    this._lastInterimAt = -Infinity;
    this._rec = null;
  }

  status(message = "") {
    return {
      running: this.running,
      restarts: this.restarts,
      gapMs: this.gapMs,
      lastError: this.lastError,
      message,
    };
  }

  start() {
    if (this.running) return;
    this.running = true;
    this._open();
    this.onStatus(this.status("listening"));
  }

  stop() {
    this.running = false;
    if (this._rec) this._rec.stop();
    this.onStatus(this.status("stopped"));
  }

  _open() {
    const rec = new this.Recognition();
    rec.lang = this.lang;
    rec.continuous = true;
    rec.interimResults = true;
    rec.maxAlternatives = 1;
    rec.onstart = () => this._onStart();
    rec.onresult = (e) => this._onResult(e);
    rec.onerror = (e) => this._onError(e);
    rec.onend = () => this._onEnd();
    this._rec = rec;
    this._firstSeen.clear();
    rec.start();
  }

  _onStart() {
    if (this._gapStart !== null) {
      this.gapMs += this.now() - this._gapStart;
      this._gapStart = null;
    }
  }

  _onResult(event) {
    const t = this.now();
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const result = event.results[i];
      const text = result[0].transcript;
      if (!this._firstSeen.has(i)) this._firstSeen.set(i, t);
      const tStart = this._firstSeen.get(i);
      if (result.isFinal) {
        this._firstSeen.delete(i);
        this._networkErrors = 0;
        this.onSegment({ text, isFinal: true, tStart, tEnd: t });
      } else if (t - this._lastInterimAt >= this.interimMs) {
        this._lastInterimAt = t;
        this.onSegment({ text, isFinal: false, tStart, tEnd: t });
      }
    }
  }

  _onError(event) {
    const error = event.error;
    this.lastError = error;
    if (error === "not-allowed" || error === "service-not-allowed") {
      this.running = false;
      this.onStatus(this.status("microphone permission denied: allow it in the site settings"));
    } else if (error === "audio-capture") {
      this.running = false;
      this.onStatus(this.status("no microphone input found"));
    } else if (error === "network") {
      this._networkErrors += 1;
      this.onStatus(this.status("network error: retrying"));
    } else {
      // no-speech, aborted: the end event restarts recognition
      this.onStatus(this.status(error));
    }
  }

  _onEnd() {
    if (!this.running) return;
    this.restarts += 1;
    this._gapStart = this.now();
    const delay = this._networkErrors
      ? RESTART_BACKOFF_MS[Math.min(this._networkErrors, RESTART_BACKOFF_MS.length) - 1]
      : 0;
    this.setTimer(() => {
      if (this.running) this._open();
    }, delay);
    this.onStatus(this.status(delay ? `restarting in ${delay / 1000} s` : "restarting"));
  }
}
