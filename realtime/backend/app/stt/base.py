"""Speech-to-text adapters (design 3.1).

Every speech source produces Segments and hands them to a SegmentSink, which
updates the session, tells the screens and logs latency. Today the source is
the browser (Web Speech segments arriving over the WebSocket). Later a server
side WhisperSource can read audio frames and feed the same sink, so the session
and the screens do not change.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

from app.core.latency import LatencyLog
from app.core.session import Session


@dataclass(frozen=True)
class Segment:
    text: str
    is_final: bool
    seq: int
    t_client: float | None = None  # client clock, seconds
    t_audio: float | None = None  # time in a recording, seconds (replays)
    lang: str = "ko-KR"
    conn: str = "server"
    clock_offset: float | None = None
    t_recv: float = field(default_factory=time.time)


class SpeechSource(Protocol):
    def segments(self) -> AsyncIterator[Segment]: ...


Broadcast = Callable[[dict], Awaitable[None]]


class SegmentSink:
    """Feeds segments into the session and reports the result."""

    def __init__(self, session: Session, broadcast: Broadcast, latency: LatencyLog):
        self.session, self.broadcast, self.latency = session, broadcast, latency

    async def submit(self, seg: Segment) -> dict | None:
        """Final segments update the session and every screen. Interim segments
        change nothing; their preview is returned for the sender only."""
        now = seg.t_audio if seg.t_audio is not None else seg.t_recv
        if not seg.is_final:
            return {
                "type": "preview",
                "seq": seg.seq,
                "candidates": self.session.preview(seg.text, now),
            }
        changed = self.session.process_final(seg.text, now=now, seq=seg.seq)
        t_done = time.time()
        t_sent = None
        if changed:
            t_sent = time.time()
            await self.broadcast(
                self.session.state() | {"seq": seg.seq, "t_recv": seg.t_recv, "t_sent": t_sent}
            )
        shown = self.session.shown
        self.latency.segment(
            conn=seg.conn,
            seq=seg.seq,
            t_client=seg.t_client,
            t_recv=seg.t_recv,
            t_detect_done=t_done,
            t_sent=t_sent,
            clock_offset=seg.clock_offset,
            shown_changed=changed,
            shown=str(shown.candidate.ref) if shown else None,
        )
        return None


async def pump(source: SpeechSource, sink: SegmentSink) -> int:
    """Run a source into a sink until it ends. Returns the number of segments."""
    n = 0
    async for seg in source.segments():
        await sink.submit(seg)
        n += 1
    return n
