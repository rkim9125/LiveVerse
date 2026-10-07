"""LLM guesses for ambiguous mentions: interface only.

Stage 6 adds Ollama and Claude implementations. They return references (never
verse text), each validated against the versification, and the screen shows
them as tentative. Until then the session uses NullResolver.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.core.models import Reference


@dataclass(frozen=True)
class Guess:
    ref: Reference
    confidence: float


class RefResolver(Protocol):
    def resolve(self, text: str, spoken: Reference | None) -> list[Guess]: ...


class NullResolver:
    def resolve(self, text: str, spoken: Reference | None) -> list[Guess]:
        return []
