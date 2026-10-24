"""Whisper decoding of one utterance."""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

MODELS = {
    "turbo": "mlx-community/whisper-large-v3-turbo",
    "medium": "mlx-community/whisper-medium-mlx",
    "small": "mlx-community/whisper-small-mlx",
}


@dataclass
class Decoded:
    text: str
    words: list[tuple[float, float, str]] = field(default_factory=list)  # utterance seconds
    seconds: float = 0.0  # time the decoding took


def drop_repetition(text: str, min_count: int = 4, share: float = 0.5) -> str:
    """ "" for a hallucinated loop: one word making up at least share of the text
    and repeated min_count times or more ("요한일서 요한일서 요한일서 ..."). Whisper
    does this on short or unclear audio, often echoing the book name prompt."""
    words = text.split()
    if len(words) < min_count:
        return text
    _, n = Counter(words).most_common(1)[0]
    return "" if n >= min_count and n / len(words) >= share else text


class Decoder(Protocol):
    def decode(self, audio: np.ndarray, words: bool = False) -> Decoded: ...


class MlxDecoder:
    """mlx-whisper on Apple Silicon. The prompt goes with every call."""

    def __init__(self, model: str = "turbo", prompt: str | None = None, language: str = "ko"):
        self.repo = MODELS.get(model, model)
        self.prompt = prompt
        self.language = language
        self.dropped = 0  # decodes thrown away as repetition loops

    def warm_up(self) -> None:
        self.decode(np.zeros(16000, dtype=np.float32))

    def decode(self, audio: np.ndarray, words: bool = False) -> Decoded:
        import mlx_whisper

        t = time.perf_counter()
        result = mlx_whisper.transcribe(
            audio,
            path_or_hf_repo=self.repo,
            language=self.language,
            initial_prompt=self.prompt,
            word_timestamps=words,
            temperature=0.0,
            condition_on_previous_text=False,
            verbose=None,
        )
        out = []
        for seg in result.get("segments", []):
            for w in seg.get("words", []) if words else []:
                out.append((float(w["start"]), float(w["end"]), w["word"]))
        raw = "".join(s["text"] for s in result.get("segments", [])).strip()
        text = drop_repetition(raw)
        self.dropped += bool(raw and not text)
        return Decoded(text, out if text else [], time.perf_counter() - t)
