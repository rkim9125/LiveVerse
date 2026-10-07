"""Settings from environment variables.

BIBLE_TEXT_PATH            Bible text file (default: data/bible_data.js, else the KJV sample)
LIVEVERSE_SHOW_THRESHOLD   confidence needed to show a candidate at once (default 0.7)
LIVEVERSE_QUOTE_SEARCH     on / off: find verses quoted without a number (default on)
LIVEVERSE_PENDING_S        seconds a chapter said in passing waits to be confirmed (default 10)
LIVEVERSE_LOG_DIR          where latency logs go (default realtime/backend/logs)
LIVEVERSE_ALLOW_REMOTE     on / off: accept clients other than localhost (default off)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _on(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "on", "true", "yes")


@dataclass(frozen=True)
class Settings:
    bible_text_path: Path | None = None
    show_threshold: float = 0.7
    quote_search: bool = True
    pending_s: float = 10.0
    log_dir: Path = BACKEND / "logs"
    allow_remote: bool = False
    max_candidates: int = 5
    max_alternatives: int = 3

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        path = env.get("BIBLE_TEXT_PATH")
        return cls(
            bible_text_path=Path(path).expanduser() if path else None,
            show_threshold=float(env.get("LIVEVERSE_SHOW_THRESHOLD", 0.7)),
            quote_search=_on(env.get("LIVEVERSE_QUOTE_SEARCH"), True),
            pending_s=float(env.get("LIVEVERSE_PENDING_S", 10.0)),
            log_dir=Path(env.get("LIVEVERSE_LOG_DIR", BACKEND / "logs")).expanduser(),
            allow_remote=_on(env.get("LIVEVERSE_ALLOW_REMOTE"), False),
        )
