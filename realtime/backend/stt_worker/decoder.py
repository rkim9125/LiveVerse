"""Whisper decoding of one utterance."""

from __future__ import annotations

import time
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


class Decoder(Protocol):
    def decode(self, audio: np.ndarray, words: bool = False) -> Decoded: ...


class MlxDecoder:
    """mlx-whisper on Apple Silicon. The prompt goes with every call."""

    def __init__(self, model: str = "turbo", prompt: str | None = None, language: str = "ko"):
        self.repo = MODELS.get(model, model)
        self.prompt = prompt
        self.language = language

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
        text = "".join(s["text"] for s in result.get("segments", [])).strip()
        return Decoded(text, out, time.perf_counter() - t)
