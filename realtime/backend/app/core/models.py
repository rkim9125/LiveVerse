"""Core value types shared by the detection pipeline."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Mode = Literal["spoken", "typed"]
Kind = Literal["absolute", "relative"]

# Confidence at or above this counts as "high" in fixtures and in the console.
HIGH_CONFIDENCE = 0.7

_REF_RE = re.compile(r"^([0-9a-z]+) (\d+)(?::(\d+)(?:-(\d+)|(\+))?)?$")


@dataclass(frozen=True)
class Reference:
    """A Bible reference. Book codes are the app abbreviations (gn, jo, 1co, ...).

    verse_start None means the whole chapter. verse_end None means a single verse.
    open_ended means "this verse and following" (16절 이하).
    """

    book: str
    chapter: int
    verse_start: int | None = None
    verse_end: int | None = None
    open_ended: bool = False

    def __str__(self) -> str:
        s = f"{self.book} {self.chapter}"
        if self.verse_start is not None:
            s += f":{self.verse_start}"
            if self.open_ended:
                s += "+"
            elif self.verse_end is not None and self.verse_end != self.verse_start:
                s += f"-{self.verse_end}"
        return s

    @classmethod
    def parse(cls, s: str) -> Reference:
        """Parse the compact form used in fixtures: 'jo 3', 'jo 3:16', 'jo 3:16-18', 'jo 3:16+'."""
        m = _REF_RE.match(s.strip())
        if not m:
            raise ValueError(f"bad reference: {s!r}")
        book, ch, v1, v2, plus = m.groups()
        return cls(
            book=book,
            chapter=int(ch),
            verse_start=int(v1) if v1 else None,
            verse_end=int(v2) if v2 else None,
            open_ended=bool(plus),
        )

    @property
    def last_verse(self) -> int | None:
        return self.verse_end if self.verse_end is not None else self.verse_start


@dataclass(frozen=True)
class Mention:
    """A detected reference inside a transcript segment."""

    ref: Reference
    kind: Kind
    matched_text: str
    span: tuple[int, int]  # character offsets into the original segment
    confidence: float

    @property
    def is_high(self) -> bool:
        return self.confidence >= HIGH_CONFIDENCE
