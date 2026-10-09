"""Cut a stream of audio frames into utterances using VAD probabilities.

The VAD itself (Silero) gives one speech probability per frame. This class
only decides where utterances start and end, so it can be tested with made up
probabilities.

  start  probability >= start_threshold for start_frames frames in a row.
         pad_s of audio before that is kept, so the first word is not clipped.
  end    probability < end_threshold for hangover_s.
  cut    an utterance reaching max_s is cut at the frame with the lowest
         probability in its last cut_search_s; the rest starts the next one.
         Sermons often run on without a pause long enough to end an utterance.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

SR = 16000


@dataclass
class SegmenterConfig:
    frame: int = 512  # samples per VAD frame (32 ms at 16 kHz, Silero's size)
    start_threshold: float = 0.5
    start_frames: int = 3
    end_threshold: float = 0.35
    hangover_s: float = 0.4
    pad_s: float = 0.2
    max_s: float = 12.0
    cut_search_s: float = 1.5


@dataclass
class Utterance:
    audio: np.ndarray
    start: float  # stream seconds of the first sample
    end: float  # stream seconds after the last sample
    cut: bool = False  # ended by max_s, not by silence


@dataclass
class Segmenter:
    config: SegmenterConfig = field(default_factory=SegmenterConfig)

    def __post_init__(self) -> None:
        c = self.config
        self._pad_frames = max(1, round(c.pad_s * SR / c.frame))
        self._hang_frames = max(1, round(c.hangover_s * SR / c.frame))
        self._max_frames = round(c.max_s * SR / c.frame)
        self._search_frames = round(c.cut_search_s * SR / c.frame)
        self.reset()

    def reset(self) -> None:
        self._frames: list[np.ndarray] = []  # current utterance, or the pad before one
        self._probs: list[float] = []
        self._first = 0  # stream index of the first frame in _frames
        self._n = 0  # frames seen
        self._active = False
        self._run = 0  # consecutive frames above start (idle) or below end (active)

    @property
    def active(self) -> bool:
        return self._active

    def current(self) -> Utterance | None:
        """The utterance so far, for interim decoding."""
        if not self._active:
            return None
        return self._make(len(self._frames))

    def push(self, frame: np.ndarray, prob: float) -> list[Utterance]:
        """Add one frame and its speech probability. Returns finished utterances."""
        self._frames.append(frame)
        self._probs.append(prob)
        self._n += 1
        c = self.config
        if not self._active:
            self._run = self._run + 1 if prob >= c.start_threshold else 0
            keep = self._pad_frames + self._run
            if len(self._frames) > keep:
                drop = len(self._frames) - keep
                del self._frames[:drop], self._probs[:drop]
                self._first += drop
            if self._run >= c.start_frames:
                self._active, self._run = True, 0
            return []
        self._run = self._run + 1 if prob < c.end_threshold else 0
        if self._run >= self._hang_frames:
            done = self._make(len(self._frames) - self._run + 1)  # keep 1 silent frame
            self._restart(len(self._frames))
            return [done]
        if len(self._frames) >= self._max_frames:
            tail = self._probs[-self._search_frames :]
            at = len(self._frames) - len(tail) + int(np.argmin(tail)) + 1
            done = self._make(at, cut=True)
            self._restart(at, stay_active=True)
            return [done]
        return []

    def flush(self) -> list[Utterance]:
        """End of the stream: return what is left of an active utterance."""
        if not self._active:
            return []
        done = self._make(len(self._frames))
        self._restart(len(self._frames))
        return [done]

    def _make(self, upto: int, cut: bool = False) -> Utterance:
        f = self.config.frame
        audio = np.concatenate(self._frames[:upto]) if upto else np.zeros(0, np.float32)
        start = self._first * f / SR
        return Utterance(audio, start, start + upto * f / SR, cut)

    def _restart(self, at: int, stay_active: bool = False) -> None:
        del self._frames[:at], self._probs[:at]
        self._first += at
        self._active, self._run = stay_active, 0
        if not stay_active:
            # Keep only the pad for the next start.
            extra = len(self._frames) - self._pad_frames
            if extra > 0:
                del self._frames[:extra], self._probs[:extra]
                self._first += extra
