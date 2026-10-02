"""Find the verse a preacher quotes word for word without saying its number.

The index is built in memory from whatever text app.core.bible_text loads:
Korean quotes only when local Korean text is present, English quotes from the
KJV sample otherwise. Nothing from the index is written to disk.

A verse matches when the segment covers enough of it (syllable trigrams for
Korean, word trigrams for English). Thresholds were tuned on the dev set.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from app.core.bible_text import BibleText
from app.core.models import Mention, Reference

MIN_GRAMS = 6  # verses with fewer trigrams are too short to identify by their words
MIN_HITS = 10  # shared trigrams needed to accept a match
MIN_COVERAGE = 0.4  # share of the verse's trigrams found in the segment
MIN_MARGIN = 0.1  # best coverage minus second best
CONF_QUOTE = 0.7

VerseKey = tuple[str, int, int]


def _ko_grams(text: str) -> set[str]:
    s = "".join(re.findall(r"[가-힣]", text))
    return {s[i : i + 3] for i in range(len(s) - 2)}


def _en_grams(text: str) -> set[str]:
    w = re.findall(r"[a-z]+", text.lower())
    return {" ".join(w[i : i + 3]) for i in range(len(w) - 2)}


@dataclass
class _Index:
    grams: dict[VerseKey, int]  # verse -> number of trigrams
    postings: dict[str, list[VerseKey]]


def _build(verses: dict[VerseKey, str], grams_of) -> _Index:
    sizes, postings = {}, defaultdict(list)
    for key, text in verses.items():
        grams = grams_of(text)
        if len(grams) < MIN_GRAMS:
            continue
        sizes[key] = len(grams)
        for g in grams:
            postings[g].append(key)
    return _Index(sizes, dict(postings))


class QuoteIndex:
    def __init__(self, bible: BibleText):
        ko, en = {}, {}
        for book, chapters in bible.books.items():
            for c, (ko_verses, en_verses) in enumerate(chapters, 1):
                for v, text in enumerate(ko_verses, 1):
                    ko[(book, c, v)] = text
                for v, text in enumerate(en_verses, 1):
                    en[(book, c, v)] = text
        self.korean = _build(ko, _ko_grams) if ko else None
        self.english = _build(en, _en_grams) if en else None

    def _best(self, index: _Index | None, grams: set[str]) -> list[tuple[float, int, VerseKey]]:
        if index is None or len(grams) < MIN_HITS:
            return []
        hits: dict[VerseKey, int] = defaultdict(int)
        for g in grams:
            for key in index.postings.get(g, ()):
                hits[key] += 1
        scored = [(n / index.grams[k], n, k) for k, n in hits.items() if n >= MIN_HITS]
        return sorted(scored, reverse=True)[:2]

    def find(self, text: str, spoken: Reference | None = None) -> Mention | None:
        """The quoted verse in text, or None.

        A verse inside the passage the preacher is already on (spoken) is not
        reported: that is reading the announced text aloud, not a quote.
        """
        best = self._best(self.korean, _ko_grams(text)) or self._best(self.english, _en_grams(text))
        if not best:
            return None
        coverage, _, (book, chapter, verse) = best[0]
        second = best[1][0] if len(best) > 1 else 0.0
        if coverage < MIN_COVERAGE or coverage - second < MIN_MARGIN:
            return None
        if spoken and _inside(spoken, book, chapter, verse):
            return None
        ref = Reference(book, chapter, verse)
        return Mention(ref, "absolute", "", (0, 0), CONF_QUOTE)


def _inside(passage: Reference, book: str, chapter: int, verse: int) -> bool:
    if (passage.book, passage.chapter) != (book, chapter) or passage.verse_start is None:
        return False
    last = passage.verse_end or passage.verse_start
    if passage.open_ended:
        last = 10_000
    return passage.verse_start <= verse <= last
