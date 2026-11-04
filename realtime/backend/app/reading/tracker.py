"""Reading confirmation (#12): which verse is the preacher reading aloud?

After a reference, preachers usually read the passage. If speech recognition
misheard the numbers ("10" / "7절" for 17절), the words read still identify the
verse. Each final segment is matched against the verses of the passage on
screen and of the spoken position (their chapters), then of the same book with
a stricter threshold, using the quote index's trigrams. The whole Bible is
left to quote search.

Outcomes:
  confirm  the verse read is inside the shown passage
  fill     a chapter is shown and one of its verses is read
  replace  the shown passage does not contain the verse read
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from app.core.models import Reference
from app.detect.quotes import QuoteIndex, _en_grams, _Index, _ko_grams
from app.reading.base import ReadingEvent

MIN_COVERAGE = 0.5  # share of the verse's trigrams read, in the passage's chapters
MIN_COVERAGE_BOOK = 0.65  # in other chapters of the same book
MIN_HITS = 6
MIN_MARGIN = 0.1
KEEP_S = 20.0  # current() reports a reading this long


@dataclass
class TextReadingTracker:
    quotes: QuoteIndex

    def __post_init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._current: ReadingEvent | None = None
        self._t = 0.0

    def current(self) -> ReadingEvent | None:
        return self._current

    def observe(
        self, text: str, now: float, spoken: Reference | None, shown: Reference | None
    ) -> list[ReadingEvent]:
        chapters = {(r.book, r.chapter) for r in (shown, spoken) if r is not None}
        if not chapters:
            return []
        found = self._match(text, lambda k: (k[0], k[1]) in chapters, MIN_COVERAGE)
        if found is None:
            books = {b for b, _ in chapters}
            found = self._match(text, lambda k: k[0] in books, MIN_COVERAGE_BOOK)
        if found is None:
            if self._current is not None and now - self._t > KEEP_S:
                self._current = None
            return []
        (book, chapter, verse), coverage = found
        ref = Reference(book, chapter, verse)
        event = ReadingEvent(_outcome(ref, shown), ref, round(min(1.0, coverage), 2))
        self._current, self._t = event, now
        return [event]

    def _match(self, text: str, in_scope, min_coverage: float):
        best = []
        for index, grams in (
            (self.quotes.korean, _ko_grams(text)),
            (self.quotes.english, _en_grams(text)),
        ):
            best = _scores(index, grams, in_scope)
            if best:
                break
        if not best:
            return None
        coverage, hits, key = best[0]
        second = best[1][0] if len(best) > 1 else 0.0
        size = round(hits / coverage)
        if coverage < min_coverage or hits < min(MIN_HITS, size) or coverage - second < MIN_MARGIN:
            return None
        return key, coverage


def _scores(index: _Index | None, grams: set[str], in_scope) -> list[tuple[float, int, tuple]]:
    if index is None or not grams:
        return []
    hits: dict[tuple, int] = defaultdict(int)
    for g in grams:
        for key in index.postings.get(g, ()):
            if in_scope(key):
                hits[key] += 1
    scored = [(n / index.grams[k], n, k) for k, n in hits.items()]
    return sorted(scored, reverse=True)[:2]


def _outcome(read: Reference, shown: Reference | None) -> str:
    if shown is None or (shown.book, shown.chapter) != (read.book, read.chapter):
        return "replace"
    if shown.verse_start is None:
        return "fill"
    last = shown.verse_end or shown.verse_start
    if shown.open_ended:
        last = 10_000
    return "confirm" if shown.verse_start <= read.verse_start <= last else "replace"
