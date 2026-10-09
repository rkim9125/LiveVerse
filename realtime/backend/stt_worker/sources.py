"""Audio sources: 512 sample float32 frames at 16 kHz."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path

import numpy as np

SR = 16000
FRAME = 512


class FileSource:
    """Part of a recording. realtime=True paces the frames like a live input
    (each frame is released when it would have finished arriving); otherwise
    they come as fast as they are used. t0 is the wall time of stream second 0."""

    def __init__(
        self, path: Path, start: float = 0.0, duration: float | None = None, realtime: bool = False
    ):
        from mlx_whisper.audio import load_audio

        audio = np.array(load_audio(str(path)), dtype=np.float32)
        a = int(start * SR)
        b = len(audio) if duration is None else min(len(audio), a + int(duration * SR))
        self.audio = audio[a:b].astype(np.float32)
        self.realtime = realtime
        self.t0: float | None = None

    async def frames(self) -> AsyncIterator[np.ndarray]:
        self.t0 = time.time()
        n = len(self.audio) // FRAME
        for i in range(n):
            if self.realtime:
                delay = self.t0 + (i + 1) * FRAME / SR - time.time()
                if delay > 0:
                    await asyncio.sleep(delay)
            yield self.audio[i * FRAME : (i + 1) * FRAME]


class DeviceSource:
    """A live input device (a microphone, or BlackHole for evaluation). Audio is
    taken at the device rate and resampled to 16 kHz."""

    def __init__(self, device: str):
        import sounddevice as sd

        info = sd.query_devices(device, "input")
        self.device = device
        self.rate = int(info["default_samplerate"])
        self.t0: float | None = None
        self._sd = sd

    async def frames(self) -> AsyncIterator[np.ndarray]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[np.ndarray] = asyncio.Queue()

        def callback(indata, frames, t, status):
            loop.call_soon_threadsafe(queue.put_nowait, indata[:, 0].copy())

        buf = np.zeros(0, np.float32)
        with self._sd.InputStream(
            device=self.device, channels=1, samplerate=self.rate, dtype="float32", callback=callback
        ):
            self.t0 = time.time()
            while True:
                chunk = await queue.get()
                buf = np.concatenate([buf, resample(chunk, self.rate)])
                while len(buf) >= FRAME:
                    yield buf[:FRAME]
                    buf = buf[FRAME:]


def resample(x: np.ndarray, rate: int) -> np.ndarray:
    """Linear resampling to 16 kHz. Enough for speech recognition."""
    if rate == SR:
        return x.astype(np.float32)
    n = int(round(len(x) * SR / rate))
    return np.interp(np.arange(n) * rate / SR, np.arange(len(x)), x).astype(np.float32)
