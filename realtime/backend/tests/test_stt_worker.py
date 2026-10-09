"""Whisper streaming worker: the parts that need no model."""

import pytest

np = pytest.importorskip("numpy")

from stt_worker.segmenter import SR, Segmenter, SegmenterConfig  # noqa: E402

F = 512
FRAME_S = F / SR


def feed(seg, probs):
    out = []
    for i, p in enumerate(probs):
        frame = np.full(F, i, dtype=np.float32)  # frame index as content
        out += seg.push(frame, p)
    return out


def frames_of(u):
    return sorted(set(int(x) for x in u.audio[::F]))


def test_utterance_starts_with_pad_and_ends_after_hangover():
    seg = Segmenter()  # pad 0.2 s = 6 frames, hangover 0.4 s = 12-13 frames
    probs = [0.0] * 20 + [0.9] * 30 + [0.0] * 20
    out = feed(seg, probs)
    assert len(out) == 1
    u = out[0]
    got = frames_of(u)
    assert got[0] == 20 - 6  # pad before the first speech frame
    assert got[-1] == 50  # one silent frame kept after the speech
    assert u.start == pytest.approx(14 * FRAME_S)
    assert not u.cut and not seg.active


def test_short_blip_does_not_start():
    seg = Segmenter()
    out = feed(seg, [0.0] * 10 + [0.9, 0.9] + [0.0] * 30)
    assert out == [] and not seg.active


def test_long_speech_is_cut_at_the_quietest_frame():
    cfg = SegmenterConfig(max_s=3.0, cut_search_s=1.0)
    seg = Segmenter(cfg)
    max_frames = round(3.0 * SR / F)
    probs = [0.9] * 150
    probs[max_frames - 10] = 0.4  # a dip inside the last second, not low enough to end
    out = feed(seg, probs)
    assert out and out[0].cut
    first = out[0]
    assert len(first.audio) // F == max_frames - 10 + 1
    assert seg.active  # the rest continues as the next utterance
    rest = seg.flush()[0]
    assert rest.start == pytest.approx(first.end)


def test_current_gives_the_utterance_so_far():
    seg = Segmenter()
    feed(seg, [0.0] * 10 + [0.9] * 10)
    cur = seg.current()
    assert cur is not None and cur.end == pytest.approx(20 * FRAME_S)
    assert Segmenter().current() is None


def test_flush_returns_unfinished_utterance():
    seg = Segmenter()
    feed(seg, [0.9] * 10)
    assert len(seg.flush()) == 1
    assert seg.flush() == []


# StreamWorker with a fake VAD and decoder: the frame value is the speech probability.

import asyncio  # noqa: E402

from stt_worker.decoder import Decoded  # noqa: E402
from stt_worker.stream import StreamWorker, WorkerConfig  # noqa: E402


class FakeDecoder:
    def __init__(self):
        self.calls = []

    def decode(self, audio, words=False):
        self.calls.append((len(audio) / SR, words))
        return Decoded(f"{len(audio) / SR:.2f}s", [(0.0, 0.1, "w")] if words else [], 0.01)


async def direct(fn, *args):
    return fn(*args)


def run_worker(probs, config=None):
    results = []

    async def sink(r):
        results.append(r)

    async def frames():
        for p in probs:
            yield np.full(F, p, dtype=np.float32)

    dec = FakeDecoder()
    worker = StreamWorker(lambda f: float(f[0]), dec, sink, config, run_decode=direct)
    asyncio.run(worker.run(frames()))
    return results, dec, worker


def test_finals_only_one_per_utterance_in_order():
    probs = [0.0] * 10 + [0.9] * 40 + [0.0] * 20 + [0.9] * 40 + [0.0] * 20
    results, dec, worker = run_worker(probs, WorkerConfig(interim=False))
    assert [(r.seq, r.is_final) for r in results] == [(1, True), (2, True)]
    assert all(words for _, words in dec.calls)  # finals ask for word times
    assert worker.stats["utterances"] == 2


def test_interims_come_every_second_and_share_the_seq():
    probs = [0.0] * 5 + [0.9] * 120 + [0.0] * 20  # about 3.8 s of speech
    results, dec, worker = run_worker(probs, WorkerConfig(interim=True, interim_s=1.0))
    interims = [r for r in results if not r.is_final]
    finals = [r for r in results if r.is_final]
    assert len(finals) == 1 and finals[0].seq == 1
    assert 2 <= len(interims) <= 4
    assert all(r.seq == 1 for r in interims)
    assert results[-1].is_final  # no interim after its final
    lengths = [r.utterance.end - r.utterance.start for r in interims]
    assert lengths == sorted(lengths)  # each interim covers more audio


def test_unfinished_utterance_is_flushed_at_the_end():
    results, _, _ = run_worker([0.9] * 50, WorkerConfig(interim=False))
    assert [r.is_final for r in results] == [True]
