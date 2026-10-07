"""Public entry point: transcript segment in, reference mentions out."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from app.core.models import Mention, Mode, Reference
from app.detect.context import resolve_all
from app.detect.normalize import normalize
from app.detect.parser import parse

# Added when the segment contains a phrase like "말씀입니다" or "let's read".
TRIGGER_BONUS = 0.1


@dataclass
class Detection:
    """mentions: what detect() returns.
    guesses: in-range guesses for a book said with numbers it does not have
      ("로마서 17장 1절" -> 7:1). Alternatives only, never shown by themselves.
    book: set when the segment ends on such a mention. The spoken position is
      then that book with no chapter (pass it back as context_book).
    """

    mentions: list[Mention] = field(default_factory=list)
    guesses: list[Mention] = field(default_factory=list)
    book: str | None = None


def detect(
    text: str,
    *,
    lang: str = "ko",
    mode: Mode = "spoken",
    context: Reference | str | None = None,
    known_books: frozenset[str] | set[str] = frozenset(),
) -> list[Mention]:
    """Find Bible references in one transcript segment. See analyze()."""
    return analyze(text, lang=lang, mode=mode, context=context, known_books=known_books).mentions


def analyze(
    text: str,
    *,
    lang: str = "ko",
    mode: Mode = "spoken",
    context: Reference | str | None = None,
    context_book: str | None = None,
    known_books: frozenset[str] | set[str] = frozenset(),
) -> Detection:
    """Find Bible references in one transcript segment.

    lang is the STT language hint. The parser reads Korean and English in any
    segment, so it is not needed yet; it is kept for the STT and LLM stages.
    context is the reference currently on the display, used for "17절",
    "다음 절" and similar. known_books are books already shown in this service;
    the displayed book is always included. They allow looser matches for
    misheard book names. context_book is a book said last with a chapter it
    does not have; it replaces context.
    """
    if isinstance(context, str):
        context = Reference.parse(context)
    if context_book is not None:
        context = None
    norm = normalize(text)
    known = frozenset(known_books) | ({context.book} if context else frozenset())
    result = parse(norm, mode, known)
    resolved, guessed, book = resolve_all(result.mentions, context, context_book)
    mentions: list[Mention] = []
    for raw, ref, kind, conf in resolved:
        if _repeats_displayed_chapter(ref, context):
            continue
        if result.trigger:
            conf = min(1.0, conf + TRIGGER_BONUS)
        if mentions and mentions[-1].ref == ref:
            continue
        start, end = norm.original_span(raw.start, raw.end)
        mentions.append(
            Mention(
                ref,
                kind,
                norm.original[start:end],
                (start, end),
                round(conf, 2),
                fuzzy_from=raw.fuzzy_from,
            )
        )
    guesses = []
    for raw, ref, kind, conf in guessed:
        start, end = norm.original_span(raw.start, raw.end)
        guesses.append(Mention(ref, kind, norm.original[start:end], (start, end), conf))
    return Detection(_mark_superseded(mentions), guesses, book)


def _repeats_displayed_chapter(ref: Reference, displayed: Reference | None) -> bool:
    """A chapter said again while a verse of it is on the display ("이사야 40장"
    after 40:27 is shown). The display already shows that chapter."""
    return (
        displayed is not None
        and displayed.verse_start is not None
        and ref.verse_start is None
        and (ref.book, ref.chapter) == (displayed.book, displayed.chapter)
    )


def _mark_superseded(mentions: list[Mention]) -> list[Mention]:
    out = []
    for i, m in enumerate(mentions):
        ref = m.ref
        later_verse = any(
            n.ref.book == ref.book and n.ref.chapter == ref.chapter and n.ref.verse_start
            for n in mentions[i + 1 :]
        )
        out.append(replace(m, superseded=True) if ref.verse_start is None and later_verse else m)
    return out
