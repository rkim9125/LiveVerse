"""Public entry point: transcript segment in, reference mentions out."""

from __future__ import annotations

from app.core.models import Mention, Mode, Reference
from app.detect.context import resolve
from app.detect.normalize import normalize
from app.detect.parser import parse

# Added when the segment contains a phrase like "말씀입니다" or "let's read".
TRIGGER_BONUS = 0.1


def detect(
    text: str,
    *,
    lang: str = "ko",
    mode: Mode = "spoken",
    context: Reference | str | None = None,
    known_books: frozenset[str] | set[str] = frozenset(),
) -> list[Mention]:
    """Find Bible references in one transcript segment.

    lang is the STT language hint. The parser reads Korean and English in any
    segment, so it is not needed yet; it is kept for the STT and LLM stages.
    context is the reference currently on the display, used for "17절",
    "다음 절" and similar. known_books are books already shown in this service;
    the displayed book is always included. They allow looser matches for
    misheard book names.
    """
    if isinstance(context, str):
        context = Reference.parse(context)
    norm = normalize(text)
    known = frozenset(known_books) | ({context.book} if context else frozenset())
    result = parse(norm, mode, known)
    mentions: list[Mention] = []
    for raw, ref, kind, conf in resolve(result.mentions, context):
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
    return mentions
