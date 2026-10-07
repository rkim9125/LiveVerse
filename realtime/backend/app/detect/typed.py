"""Parse a reference typed by a person (search box, review tool, REST)."""

from __future__ import annotations

import re

from app.core.models import Reference
from app.detect import versification
from app.detect.books import BY_ABBREV, lookup
from app.detect.pipeline import detect

_REF_TAIL = re.compile(r"(.+?)\s*(\d+(?::\d+(?:-\d+)?\+?)?)")


def parse_query(text: str) -> Reference:
    """'mt 22:1-14', 'matthew 22:1-14', '마태복음 22:1-14', '마 22:1-14',
    '마태복음 22장 1절부터 14절까지' -> Reference. Raises ValueError."""
    part = " ".join(text.strip().lower().split())
    if not part:
        raise ValueError("empty reference")
    ref = None
    m = _REF_TAIL.fullmatch(part)
    if m:
        name = m.group(1).strip()
        book = name if name in BY_ABBREV else lookup(name, "typed")
        if book:
            ref = Reference.parse(f"{book} {m.group(2)}")
    if ref is None:
        found = detect(part, mode="typed")
        if len(found) != 1:
            raise ValueError(
                f"{text!r}: write it like mt 22:1-14, matthew 22:1-14 or 마태복음 22:1-14"
            )
        ref = found[0].ref
    verses = versification.verse_count(ref.book, ref.chapter)
    if verses is None:
        raise ValueError(f"{text!r}: no such chapter")
    if ref.last_verse is not None and ref.last_verse > verses:
        raise ValueError(f"{text!r}: chapter {ref.chapter} has {verses} verses")
    return ref
