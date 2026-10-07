"""Resolve relative references ("17절", "다음 절", "next chapter") against context.

Context inside a segment is the last reference found earlier in the same segment
("요한복음 3장 16절, 그리고 17절"). Otherwise it is the spoken position passed in.
With no context, relative mentions produce nothing.

A book said with a chapter it does not have ("로마서 17장") leaves only the book
as context: a later "3장" is read as 로마서 3장, while verse-relative mentions
("1절", "다음 절") have no chapter to attach to and produce nothing. They never
borrow the previous book's chapter.
"""

from __future__ import annotations

from app.core.models import Kind, Reference
from app.detect import versification
from app.detect.parser import RawMention, _Spec, make_absolute

CONF_SEGMENT = 0.85  # resolved against a reference said earlier in the same segment
CONF_DISPLAYED = 0.7  # resolved against the displayed reference
CONF_CHAPTER_ONLY = 0.6  # "4장으로 넘어가서": book taken from context
CONF_BOUNDARY = 0.4  # "다음 절" after the last verse of a chapter

Resolved = tuple[RawMention, Reference, Kind, float]


def _next_verse(base: Reference, conf: float) -> tuple[Reference, float] | None:
    cur = base.last_verse
    if cur is None:
        return None
    count = versification.verse_count(base.book, base.chapter)
    if count and cur + 1 <= count:
        return Reference(base.book, base.chapter, cur + 1), conf
    if versification.verse_count(base.book, base.chapter + 1):
        return Reference(base.book, base.chapter + 1, 1), CONF_BOUNDARY
    return None


def _prev_verse(base: Reference, conf: float) -> tuple[Reference, float] | None:
    cur = base.verse_start
    if cur is None:
        return None
    if cur > 1:
        return Reference(base.book, base.chapter, cur - 1), conf
    prev_count = versification.verse_count(base.book, base.chapter - 1)
    if prev_count:
        return Reference(base.book, base.chapter - 1, prev_count), CONF_BOUNDARY
    return None


def _resolve_one(raw: RawMention, base: Reference, conf: float) -> tuple[Reference, float] | None:
    book = base.book
    if raw.op == "verse":
        spec = _Spec(base.chapter, raw.verse_start, raw.verse_end, raw.open_ended)
        made = make_absolute(book, spec)
        return (made[0], conf) if made else None
    if raw.op == "chapter":
        spec = _Spec(raw.chapter, raw.verse_start, raw.verse_end, raw.open_ended, raw.last_verse)
        made = make_absolute(book, spec)
        if made is None:
            return None
        ref = made[0]
        return ref, (CONF_CHAPTER_ONLY if ref.verse_start is None else conf)
    if raw.op == "next_verse":
        return _next_verse(base, conf)
    if raw.op == "prev_verse":
        return _prev_verse(base, conf)
    if raw.op == "next_chapter":
        if versification.verse_count(book, base.chapter + 1):
            return Reference(book, base.chapter + 1), conf
        return None
    if raw.op == "last_verse":
        count = versification.verse_count(book, base.chapter)
        return (Reference(book, base.chapter, count), conf) if count else None
    raise ValueError(f"unknown op {raw.op!r}")


def resolve(raws: list[RawMention], displayed: Reference | None) -> list[Resolved]:
    return resolve_all(raws, displayed)[0]


def resolve_all(
    raws: list[RawMention], displayed: Reference | None, book: str | None = None
) -> tuple[list[Resolved], list[Resolved], str | None]:
    """Returns the resolved mentions, the guesses for out of range numbers, and
    the book left as context if the segment ends on an out of range mention."""
    out: list[Resolved] = []
    guesses: list[Resolved] = []
    segment: Reference | None = None
    book_only = book  # a book whose chapter is unknown
    blocked = False  # an unconfirmed book name was said: no context for the rest
    for raw in raws:
        if raw.op == "block":
            segment, blocked, book_only = None, True, None
            continue
        if raw.op == "out_of_range":
            segment, blocked, book_only = None, False, raw.book
            if raw.ref is not None:
                guesses.append((raw, raw.ref, "absolute", raw.confidence))
            continue
        if raw.op == "abs":
            blocked, book_only = False, None
            out.append((raw, raw.ref, "absolute", raw.confidence))
            segment = raw.ref
            continue
        if book_only is not None and segment is None:
            if raw.op != "chapter":
                continue  # no chapter to attach a verse to
            spec = _Spec(
                raw.chapter, raw.verse_start, raw.verse_end, raw.open_ended, raw.last_verse
            )
            made = make_absolute(book_only, spec)
            if made is None:
                continue
            ref = made[0]
            conf = CONF_CHAPTER_ONLY if ref.verse_start is None else CONF_DISPLAYED
            out.append((raw, ref, "relative", conf))
            segment, book_only = ref, None
            continue
        base = segment or (None if blocked else displayed)
        if base is None:
            continue  # no context: nothing to resolve against
        resolved = _resolve_one(raw, base, CONF_SEGMENT if segment else CONF_DISPLAYED)
        if resolved is None:
            continue
        ref, conf = resolved
        out.append((raw, ref, "relative", conf))
        segment = ref
    return out, guesses, book_only
