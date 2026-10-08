// WebSocket client for the backend (design 3.14).
//
//   const sock = new LiveVerseSocket(url, { onState, onPreview, onStatus, onError });
//   sock.connect();
//   sock.sendTranscript({ seq, text, isFinal, tEnd, tAudio });
//   sock.rendered(seq, fromInterim);   // after the screen drew a state

const RECONNECT_MS = [1000, 2000, 4000, 8000];

export class LiveVerseSocket {
  constructor(
    url,
    {
      onState = () => {},
      onPreview = () => {},
      onStatus = () => {},
      onError = () => {},
      WebSocketImpl = globalThis.WebSocket,
      now = () => Date.now(),
      setTimer = (fn, ms) => setTimeout(fn, ms),
    } = {},
  ) {
    Object.assign(this, { url, onState, onPreview, onStatus, onError, WebSocketImpl, now, setTimer });
    this.ws = null;
    this.closed = false;
    this.attempts = 0;
    this.queue = [];
  }

  connect() {
    this.closed = false;
    const ws = new this.WebSocketImpl(this.url);
    this.ws = ws;
    ws.onopen = () => {
      this.attempts = 0;
      this.onStatus({ connected: true });
      for (let i = 0; i < 5; i++) this._send({ type: "ping", t_client: this.now() / 1000 });
      for (const msg of this.queue.splice(0)) this._send(msg);
    };
    ws.onmessage = (event) => this._receive(event.data);
    ws.onclose = () => {
      this.onStatus({ connected: false });
      if (this.closed) return;
      const delay = RECONNECT_MS[Math.min(this.attempts, RECONNECT_MS.length - 1)];
      this.attempts += 1;
      this.setTimer(() => this.connect(), delay);
    };
    ws.onerror = () => {};
  }

  close() {
    this.closed = true;
    if (this.ws) this.ws.close();
  }

  _receive(data) {
    let msg;
    try {
      msg = JSON.parse(data);
    } catch {
      return;
    }
    if (msg.type === "state") this.onState(msg);
    else if (msg.type === "preview") this.onPreview(msg);
    else if (msg.type === "error") this.onError(msg.message);
  }

  _send(msg) {
    if (this.ws && this.ws.readyState === 1) {
      this.ws.send(JSON.stringify(msg));
      return true;
    }
    return false;
  }

  send(msg) {
    if (!this._send(msg) && msg.type === "transcript" && msg.is_final) {
      this.queue.push(msg); // keep finals until the connection is back
    }
  }

  sendTranscript({ seq, text, isFinal, tEnd, tAudio = null, lang = "ko-KR" }) {
    const msg = { type: "transcript", seq, text, is_final: isFinal, lang, t_client: tEnd / 1000 };
    if (tAudio !== null) msg.t_audio = tAudio;
    this.send(msg);
  }

  rendered(seq, fromInterim = false) {
    if (seq !== null && seq !== undefined) {
      this._send({ type: "rendered", seq, t_render: this.now() / 1000, from_interim: fromInterim });
    }
  }
}
