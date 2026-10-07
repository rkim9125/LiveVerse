"""Verse text for the interpreter screen, loaded at run time from data/."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core import bible_text
from app.core.models import Reference
from app.detect import versification
from app.detect.books import BY_ABBREV


@dataclass(frozen=True)
class Verse:
    num: int
    ko: str
    en: str


class BibleStore:
    def __init__(self, text: bible_text.BibleText):
        self.text = text
        names = text.meta.get("names", {})
        self.names = {"ko": names.get("ko", ""), "en": names.get("en", "")}
        self.has_korean = text.has_korean

    @classmethod
    def load(cls, path: Path | None = None) -> BibleStore:
        return cls(bible_text.load(path))

    def info(self) -> dict:
        """What was loaded. Never includes verse text."""
        books = self.text.books
        return {
            "file": self.text.path.name,
            "title": self.text.meta.get("title", ""),
            "names": self.names,
            "korean": self.has_korean,
            "books": len(books),
            "verses": sum(len(en) or len(ko) for chs in books.values() for ko, en in chs),
        }

    def verses(self, ref: Reference) -> list[Verse]:
        chapters = self.text.books.get(ref.book)
        if not chapters or not 1 <= ref.chapter <= len(chapters):
            raise KeyError(str(ref))
        ko, en = chapters[ref.chapter - 1]
        count = versification.verse_count(ref.book, ref.chapter) or max(len(ko), len(en))
        first = ref.verse_start or 1
        last = count if ref.verse_start is None or ref.open_ended else ref.last_verse
        last = min(last, count)
        return [
            Verse(v, ko[v - 1] if v <= len(ko) else "", en[v - 1] if v <= len(en) else "")
            for v in range(first, last + 1)
        ]

    @staticmethod
    def label(ref: Reference) -> dict:
        book = BY_ABBREV[ref.book]
        tail = str(ref)[len(ref.book) + 1 :]
        return {"en": f"{book.en} {tail}", "ko": f"{book.ko} {tail}"}
