"""Reading confirmation (#12) and reading follow (#13): interface only.

Stage 5 implements a tracker that matches what the preacher reads aloud against
the Bible text (current chapter, then book, then whole Bible) and reports which
verse is being read. Until then the session uses NullReadingTracker.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from app.core.models import Reference

Outcome = Literal["confirm", "fill", "replace", "follow"]


@dataclass(frozen=True)
class ReadingEvent:
    outcome: Outcome
    ref: Reference  # the verse being read
    confidence: float


class ReadingTracker(Protocol):
    def observe(
        self, text: str, now: float, spoken: Reference | None, shown: Reference | None
    ) -> list[ReadingEvent]: ...

    def current(self) -> ReadingEvent | None: ...

    def reset(self) -> None: ...


class NullReadingTracker:
    def observe(
        self, text: str, now: float, spoken: Reference | None, shown: Reference | None
    ) -> list[ReadingEvent]:
        return []

    def current(self) -> ReadingEvent | None:
        return None

    def reset(self) -> None:
        pass
