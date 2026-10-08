"""Speech-to-text adapters (design 3.1).

Every speech source produces Segments and hands them to a SegmentSink, which
updates the session, tells the screens and logs latency. Today the source is
the browser (Web Speech segments arriving over the WebSocket). Later a server
side WhisperSource can read audio frames and feed the same sink, so the session
and the screens do not change.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field, replace
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
        self._timer: asyncio.TimerHandle | None = None

    def close(self) -> None:
        self._cancel_timer()

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    async def _send(self, seg: Segment, interim: bool, t_done: float) -> None:
        t_sent = time.time()
        await self.broadcast(
            self.session.state()
            | {"seq": seg.seq, "t_recv": seg.t_recv, "t_sent": t_sent, "from_interim": interim}
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
            shown_changed=True,
            shown=str(shown.candidate.ref) if shown else None,
            reason=self.session.history[-1]["reason"] if self.session.history else None,
            interim=interim,
        )

    def _schedule_hold(self, seg: Segment, now: float) -> None:
        """Show the watched verse once it has been held long enough, even if no
        further interim arrives (the preacher paused after saying it)."""
        self._cancel_timer()
        due = self.session.interim_due()
        if due is None:
            return

        async def fire() -> None:
            self._timer = None
            t0 = time.time()
            if self.session.tick(due):
                # No new segment arrived: the speech time is unknown (t_client None).
                await self._send(replace(seg, t_client=None, t_recv=t0), True, time.time())

        loop = asyncio.get_running_loop()
        self._timer = loop.call_later(max(0.0, due - now), lambda: loop.create_task(fire()))

    async def submit(self, seg: Segment) -> dict | None:
        """Final segments update the session and every screen. Interim segments
        can show a stable verse (marked interim); their preview is returned for
        the sender."""
        now = seg.t_audio if seg.t_audio is not None else seg.t_recv
        if not seg.is_final:
            if self.session.process_interim(seg.text, now, seq=seg.seq):
                self._cancel_timer()
                await self._send(seg, True, time.time())
            else:
                self._schedule_hold(seg, now)
            return {
                "type": "preview",
                "seq": seg.seq,
                "candidates": self.session.preview(seg.text, now),
            }
        self._cancel_timer()
        changed = self.session.process_final(seg.text, now=now, seq=seg.seq)
        t_done = time.time()
        t_sent = None
        if changed:
            t_sent = time.time()
            await self.broadcast(
                self.session.state()
                | {"seq": seg.seq, "t_recv": seg.t_recv, "t_sent": t_sent, "from_interim": False}
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
            reason=self.session.history[-1]["reason"] if self.session.history else None,
        )
        return None


async def pump(source: SpeechSource, sink: SegmentSink) -> int:
    """Run a source into a sink until it ends. Returns the number of segments."""
    n = 0
    async for seg in source.segments():
        await sink.submit(seg)
        n += 1
    return n
