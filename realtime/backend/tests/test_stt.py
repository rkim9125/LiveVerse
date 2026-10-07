"""Speech sources feed a SegmentSink; swapping the source changes nothing else."""

import asyncio

from app.core.latency import LatencyLog
from app.core.session import Session
from app.stt.base import Segment, SegmentSink, pump


class FakeServerSource:
    """Stands in for a future server side Whisper source."""

    def __init__(self, items):
        self.items = items

    async def segments(self):
        for i, (t, text) in enumerate(self.items, 1):
            yield Segment(text=text, is_final=True, seq=i, t_audio=t, conn="whisper")


def test_a_server_source_drives_the_same_session(settings, store, tmp_path):
    session = Session(store, settings)
    sent = []

    async def broadcast(message):
        sent.append(message)

    sink = SegmentSink(session, broadcast, LatencyLog(tmp_path))
    source = FakeServerSource(
        [(0, "요한복음 3장 16절 말씀입니다"), (6, "17절도 보시면"), (9, "오늘도")]
    )
    assert asyncio.run(pump(source, sink)) == 3
    assert [m["shown"]["ref"] for m in sent] == ["jo 3:16", "jo 3:17"]
    assert LatencyLog(tmp_path).summary()["segments"] == 3


def test_interim_returns_a_preview_and_changes_nothing(settings, store, tmp_path):
    session = Session(store, settings)

    async def broadcast(message):
        raise AssertionError("interim must not broadcast")

    sink = SegmentSink(session, broadcast, LatencyLog(tmp_path))
    reply = asyncio.run(sink.submit(Segment(text="로마서 8장 28절", is_final=False, seq=1)))
    assert reply["type"] == "preview" and reply["candidates"][0]["ref"] == "rm 8:28"
    assert session.shown is None
