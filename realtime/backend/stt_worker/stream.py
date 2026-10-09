"""Frames in, interim and final segments out.

Each frame goes through the VAD and the segmenter. While an utterance is in
progress, the audio so far is decoded every interim_s for an interim segment.
When the utterance ends, it is decoded once more with word times for the final.
Decoding runs in one background thread (one GPU); finals go before interims,
and only the latest interim request is kept, so decoding never falls behind
the audio by more than one call.

An utterance and its interims share a sequence number, as in the browser.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from stt_worker.decoder import Decoded, Decoder
from stt_worker.segmenter import Segmenter, SegmenterConfig, Utterance


@dataclass
class WorkerConfig:
    segmenter: SegmenterConfig = field(default_factory=SegmenterConfig)
    interim: bool = True
    interim_s: float = 1.0  # decode the utterance so far after this much new audio
    interim_min_s: float = 0.5  # no interim for less audio than this


@dataclass
class Result:
    seq: int
    is_final: bool
    utterance: Utterance
    decoded: Decoded


class Sink(Protocol):
    async def __call__(self, result: Result) -> None: ...


class StreamWorker:
    def __init__(
        self,
        vad: Callable[[np.ndarray], float],
        decoder: Decoder,
        sink: Callable[[Result], Awaitable[None]],
        config: WorkerConfig | None = None,
        run_decode: Callable | None = None,
    ):
        self.vad, self.decoder, self.sink = vad, decoder, sink
        self.config = config or WorkerConfig()
        self.segmenter = Segmenter(self.config.segmenter)
        # Tests pass a direct call; the real worker decodes in a thread.
        self._run_decode = run_decode or asyncio.to_thread
        self._finals: deque[tuple[int, Utterance]] = deque()
        self._interim: tuple[int, Utterance] | None = None
        self._seq = 1  # sequence number of the utterance in progress
        self._last_interim_end = 0.0
        self._wake = asyncio.Event()
        self._closing = False
        self.stats = {"utterances": 0, "cuts": 0, "interims": 0, "dropped_interims": 0}

    async def run(self, frames: AsyncIterator[np.ndarray]) -> None:
        loop_task = asyncio.create_task(self._decode_loop())
        try:
            async for frame in frames:
                self._push(frame, self.vad(frame))
                await asyncio.sleep(0)  # let the decode loop pick up work
            for u in self.segmenter.flush():
                self._finish(u)
        finally:
            self._closing = True
            self._wake.set()
            await loop_task

    def _push(self, frame: np.ndarray, prob: float) -> None:
        for u in self.segmenter.push(frame, prob):
            self._finish(u)
        if not (self.config.interim and self.segmenter.active):
            return
        cur = self.segmenter.current()
        long_enough = cur.end - cur.start >= self.config.interim_min_s
        if (
            long_enough
            and cur.end - max(self._last_interim_end, cur.start) >= self.config.interim_s
        ):
            if self._interim is not None:
                self.stats["dropped_interims"] += 1
            self._interim = (self._seq, cur)
            self._last_interim_end = cur.end
            self._wake.set()

    def _finish(self, u: Utterance) -> None:
        self._finals.append((self._seq, u))
        self.stats["utterances"] += 1
        self.stats["cuts"] += u.cut
        if self._interim is not None and self._interim[0] == self._seq:
            self._interim = None  # the final covers it
        self._seq += 1
        self._last_interim_end = u.end
        self._wake.set()

    async def _decode_loop(self) -> None:
        while True:
            if self._finals:
                seq, u = self._finals.popleft()
                decoded = await self._run_decode(self.decoder.decode, u.audio, True)
                await self.sink(Result(seq, True, u, decoded))
            elif self._interim is not None:
                seq, u = self._interim
                self._interim = None
                decoded = await self._run_decode(self.decoder.decode, u.audio, False)
                if seq == self._seq:  # the utterance is still in progress
                    self.stats["interims"] += 1
                    await self.sink(Result(seq, False, u, decoded))
                else:
                    self.stats["dropped_interims"] += 1  # its final is on the way
            elif self._closing:
                return
            else:
                self._wake.clear()
                await self._wake.wait()
