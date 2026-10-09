"""Silero VAD: speech probability for each 512 sample frame at 16 kHz."""

from __future__ import annotations

import numpy as np


class SileroVAD:
    def __init__(self) -> None:
        import torch
        from silero_vad import load_silero_vad

        torch.set_num_threads(1)
        self._torch = torch
        self.model = load_silero_vad(onnx=False)

    def __call__(self, frame: np.ndarray) -> float:
        with self._torch.no_grad():
            return float(self.model(self._torch.from_numpy(frame), 16000).item())

    def reset(self) -> None:
        self.model.reset_states()
