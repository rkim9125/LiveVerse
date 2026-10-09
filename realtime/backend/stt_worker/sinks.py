"""Where results go: the server's /ws, and a record for evaluation."""

from __future__ import annotations

import asyncio
import json
import statistics
import time

from stt_worker.stream import Result


class WsSink:
    """Sends segments to the server like the browser does."""

    def __init__(self, url: str, lang: str = "ko-KR"):
        self.url, self.lang = url, lang
        self.sent = 0

    async def __aenter__(self) -> WsSink:
        import websockets

        self.ws = await websockets.connect(self.url, max_size=None)
        self._reader = asyncio.create_task(self._drain())
        for _ in range(5):  # clock offset samples (same machine, but the server expects them)
            await self.ws.send(json.dumps({"type": "ping", "t_client": time.time()}))
        return self

    async def __aexit__(self, *exc) -> None:
        await self.ws.close()
        self._reader.cancel()

    async def _drain(self) -> None:
        try:
            async for _ in self.ws:  # state broadcasts and pongs are not needed here
                pass
        except Exception:
            pass

    async def __call__(self, r: Result) -> None:
        msg = {
            "type": "transcript",
            "seq": r.seq,
            "text": r.decoded.text,
            "is_final": r.is_final,
            "lang": self.lang,
            "t_client": time.time(),
        }
        await self.ws.send(json.dumps(msg, ensure_ascii=False))
        self.sent += 1


class RecordSink:
    """Keeps the finals (and timing) for scoring.

    Segment times are stream seconds plus offset: the clip start for a file
    (recording seconds), or the wall time of stream second 0 for a live device
    (epoch seconds, the browser capture format)."""

    def __init__(self, offset: float = 0.0):
        self.offset = offset
        self.t0: float | None = None  # wall time of stream second 0, for lags
        self.finals: list[dict] = []
        self.decode = {"final": [], "interim": []}
        self.lag: list[float] = []  # utterance end to result, live only

    async def __call__(self, r: Result) -> None:
        kind = "final" if r.is_final else "interim"
        self.decode[kind].append(r.decoded.seconds)
        if self.t0 is not None and r.is_final:
            self.lag.append(time.time() - (self.t0 + r.utterance.end))
        if not r.is_final:
            return
        u, o = r.utterance, self.offset
        seg = {"start": round(o + u.start, 2), "end": round(o + u.end, 2), "text": r.decoded.text}
        if r.decoded.words:
            seg["words"] = [
                {"start": round(o + u.start + a, 2), "end": round(o + u.start + b, 2), "word": w}
                for a, b, w in r.decoded.words
            ]
        if u.cut:
            seg["cut"] = True
        self.finals.append(seg)

    def stats(self) -> dict:
        def ms(v: list[float]) -> dict | None:
            if not v:
                return None
            s = sorted(v)
            return {
                "n": len(s),
                "p50_ms": round(statistics.median(s) * 1000),
                "p95_ms": round(s[min(len(s) - 1, round(0.95 * (len(s) - 1)))] * 1000),
                "max_ms": round(s[-1] * 1000),
            }

        lengths = sorted(s["end"] - s["start"] for s in self.finals)
        return {
            "decode_final": ms(self.decode["final"]),
            "decode_interim": ms(self.decode["interim"]),
            "utterances": {
                "n": len(lengths),
                "p50_s": round(statistics.median(lengths), 1) if lengths else None,
                "max_s": round(lengths[-1], 1) if lengths else None,
            },
            "end_to_final": ms(self.lag),
        }
