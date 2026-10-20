"""References split across segments.

Preachers pause while finding a passage, and speech recognition ends a segment
at each pause, so one reference can arrive in pieces:

  "룻기" / "2장 1절"            the book at the end of one segment, the chapter
                               at the start of the next
  "룻기 이장" / "1절부터" / "3절까지"
                               a range whose end comes in a later segment

Carry remembers the end of the last final segment for window_s seconds:

  lead_book()  the book a segment ended on, for analyze(lead_book=...)
  join()       "N절까지" right after "M절부터" of the same chapter becomes M-N
  update()     after each final segment

Filler segments with no reference ("어", "자") keep what is carried.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.core.models import Mention, Reference


@dataclass
class Carry:
    window_s: float = 15.0

    def __post_init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._open: Mention | None = None
        self._open_t = 0.0
        self._book: str | None = None
        self._book_t = 0.0

    def lead_book(self, now: float) -> str | None:
        return self._book if self._book and now - self._book_t <= self.window_s else None

    def join(self, mentions: list[Mention], now: float) -> list[Mention]:
        """mentions with the first one widened to a range, if it ends one that
        the previous segment opened. Does not change the carry."""
        start = self._open
        if start is None or not mentions or now - self._open_t > self.window_s:
            return mentions
        first, s = mentions[0], start.ref
        r = first.ref
        if not (
            first.until
            and first.kind == "relative"
            and r.verse_end is None
            and (r.book, r.chapter) == (s.book, s.chapter)
            and r.verse_start is not None
            and r.verse_start > s.verse_start
        ):
            return mentions
        joined = replace(
            first,
            ref=Reference(r.book, r.chapter, s.verse_start, r.verse_start),
            confidence=max(first.confidence, start.confidence),
            until=False,
        )
        return [joined, *mentions[1:]]

    def update(self, mentions: list[Mention], trailing_book: str | None, now: float) -> None:
        if mentions:
            last = mentions[-1]
            self._open, self._open_t = (last, now) if last.open_start else (None, 0.0)
            self._book = None
        if trailing_book:
            self._book, self._book_t = trailing_book, now
