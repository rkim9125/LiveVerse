"""References split across segments.

Preachers pause while finding a passage, and speech recognition ends a segment
at each pause, so one reference can arrive in pieces:

  "오늘 본문은 룻기" / "2장 1절"    a book, then its chapter
  "룻기 2장" / "7절 입니다"        a chapter, then its verse
  "1절부터" / "3절까지"            a range
  "19절" / "20절을 보시겠습니다"    verses in a row, to be read

Carry remembers the end of the last final segment for window_s seconds:

  lead_book()  the book a segment ended on, for analyze(lead_book=...)
  join()       the first mention of a segment joined to the last mention of
               the previous one: a chapter and its verse become that verse,
               "M절부터" and "N절까지", or verses in a row (M, M+1), become
               M-N. joined_prev then says the previous mention is part of this
               one and should not count, or be listed, on its own.
  update()     after each final segment

Filler segments with no reference ("어", "자") keep what is carried.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from app.core.models import Mention, Reference

# A phrase that announces reading ("20절을 보시겠습니다", "같이 읽겠습니다"). Not
# "보시면" or "말씀": those also go with moving on to the next verse.
_READ_RE = re.compile(r"보시겠|보겠습니다|읽겠|읽어\s*보|같이\s*보|함께\s*보")
RUN_WINDOW_S = 8.0  # verses in a row are a range only when said close together


def announces_reading(text: str) -> bool:
    return bool(_READ_RE.search(text))


@dataclass
class Carry:
    window_s: float = 15.0
    # "룻기 2장" / "7절 입니다": a chapter at the end of one final and a verse of
    # it at the start of the next are one reference.
    join_chapter: bool = True
    # "19절" / "20절", "1절" / "5절까지": verses in a row across finals are a range.
    join_runs: bool = True

    def __post_init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._last: Mention | None = None  # last mention of the last final with any
        self._last_t = 0.0
        self._book: str | None = None
        self._book_t = 0.0
        # Set by join(): the first mention continues the previous final's last
        # one, which should then not count on its own.
        self.joined_prev = False

    def lead_book(self, now: float) -> str | None:
        return self._book if self._book and now - self._book_t <= self.window_s else None

    def join(self, mentions: list[Mention], now: float, announced: bool = False) -> list[Mention]:
        """mentions with the first one joined to the previous final's last
        mention, when they are pieces of one reference. Does not change the
        carry; sets joined_prev. announced: this segment has a reading phrase
        ("20절을 보시겠습니다"), which makes M, M+1 a range to read rather than
        moving on to the next verse."""
        self.joined_prev = False
        prev = self._last
        if prev is None or not mentions or now - self._last_t > self.window_s:
            return mentions
        first, p = mentions[0], prev.ref
        r = first.ref
        if not (
            first.kind == "relative"
            and r.verse_start is not None
            and r.verse_end is None
            and (r.book, r.chapter) == (p.book, p.chapter)
        ):
            return mentions
        if p.verse_start is None:
            if not self.join_chapter:
                return mentions
            joined = first  # the verse already resolves to that chapter
        else:
            if p.verse_end is not None or p.open_ended or r.verse_start <= p.verse_start:
                return mentions
            opened = prev.open_start and first.until  # "1절부터" / "3절까지"
            next_one = (
                r.verse_start == p.verse_start + 1
                and announced
                and now - self._last_t <= RUN_WINDOW_S
            )
            run = self.join_runs and (first.until or next_one)
            if not (opened or run):
                return mentions
            joined = replace(
                first,
                ref=Reference(r.book, r.chapter, p.verse_start, r.verse_start),
                confidence=max(first.confidence, prev.confidence),
                until=False,
            )
        self.joined_prev = True
        return [joined, *mentions[1:]]

    def update(self, mentions: list[Mention], trailing_book: str | None, now: float) -> None:
        if mentions:
            self._last, self._last_t = mentions[-1], now
            self._book = None
        if trailing_book:
            self._book, self._book_t = trailing_book, now
