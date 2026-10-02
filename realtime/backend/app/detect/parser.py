"""Find Bible reference mentions in a normalized transcript segment.

The parser tokenizes the normalized text, then reads references off the token
stream. Absolute references (book + chapter) are validated against the
versification here. Relative ones ("17절", "다음 절") are returned as operations
for app.detect.context to resolve.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cache

from app.core.models import Mode, Reference
from app.detect import versification
from app.detect.books import book_regex, fuzzy_lookup, looks_like_book, lookup
from app.detect.normalize import Normalized

# Confidence for absolute references. Relative ones are scored in context.py.
CONF_VERSE = 0.9
CONF_CHAPTER = 0.75
CONF_FALLBACK = 0.4
FUZZY_PENALTY = 0.15  # a near-match book name is less certain than an exact one

# How far (in normalized characters) a book name can be from a later "3장"
# and still apply to it: "요한복음을 펴시면 3장 16절".
_PENDING_BOOK_WINDOW = 20

_TOKEN_SPECS = [
    ("SENT", r"[.?!\n]"),
    ("HYMN", r"새\s*찬송가|찬송가|찬송(?=\s*\d)|(?<![a-z])hymns?(?![a-z])"),
    (
        "NEXT_V",
        r"(?:그\s*)?다음\s*절|이어지는\s*절"
        r"|(?<![a-z])(?:the\s+)?(?:next|following)\s+verse(?![a-z])",
    ),
    ("PREV_V", r"앞\s*절|이전\s*절|(?<![a-z])(?:the\s+)?previous\s+verse(?![a-z])"),
    ("NEXT_CH", r"다음\s*장(?!로)|(?<![a-z])(?:the\s+)?next\s+chapter(?![a-z])"),
    ("LAST_V", r"마지막\s*절|(?<![a-z])(?:the\s+)?last\s+verse(?![a-z])"),
    ("OPEN", r"이하|(?<![a-z])and\s+following(?![a-z])"),
    ("EN_CH_ORD", r"\d+th\s+chapter(?:\s+of)?(?![a-z])"),
    ("EN_V_ORD", r"\d+th\s+verse(?![a-z])"),
    ("EN_CH", r"(?<![a-z])chapters?\s+\d+"),
    ("EN_V", r"(?<![a-z])verses?\s+\d+"),
    ("BOOK", None),  # filled per mode
    # An unknown word right before a chapter number: maybe a misheard book name.
    ("NAME", r"(?<![가-힣\d])[가-힣]{2,6}?(?=(?:의|에서|에|을|를|은|는|로)?\s*\d+\s*(?:장|편|:))"),
    ("KO_CH", r"\d+\s*(?:장|편)(?!로|막|짜리|지|안)"),
    ("KO_V", r"\d+\s*절(?!기)"),
    ("NUM", r"\d+(?:th)?"),
    ("COLON", r":"),
    ("RANGE", r"-|에서부터|부터|에서|내지|(?<![a-z])(?:through|thru|to|until)(?![a-z])"),
]

_TRIGGER_RE = re.compile(
    r"말씀|읽겠|읽어|읽으|보시면|보시겠|보겠습니다|펴시|펴\s*주|찾아|본문"
    r"|let'?s\s+read|we\s+read|turn\s+(?:with\s+me\s+)?to|it\s+says|open\s+your\s+bibles?"
)
_PARTICLE_GAP_RE = re.compile(r"[\s,]*(?:을|를|은|는|의|에|으로|로|도|만)?[\s,]*")
_NUMBER_TOKENS = ("NUM", "KO_V", "EN_V", "EN_V_ORD")
# Between verses listed in a row: "19절 20절", "19절과 20절", "16절, 17절, 그리고 18절".
_LIST_GAP_RE = re.compile(r"[\s,]*(?:과|와|그리고|및)?[\s,]*")


@dataclass
class Token:
    type: str
    start: int
    end: int
    text: str
    value: int | None = None
    ordinal: bool = False


@dataclass
class RawMention:
    """A reference found in the text, before relative references are resolved.

    op is "abs" for an absolute reference (ref is set), or one of "verse",
    "chapter", "next_verse", "prev_verse", "next_chapter", "last_verse".
    "block" marks a chapter said after an unconfirmed book name: it is not
    resolved, and relative mentions after it in the segment are dropped.
    start and end are offsets into the normalized text.
    """

    op: str
    start: int
    end: int
    ref: Reference | None = None
    chapter: int | None = None
    verse_start: int | None = None
    verse_end: int | None = None
    open_ended: bool = False
    last_verse: bool = False
    confidence: float = 0.0
    fuzzy_from: str | None = None


@dataclass
class ParseResult:
    mentions: list[RawMention] = field(default_factory=list)
    trigger: bool = False


@dataclass
class _Spec:
    chapter: int | None
    verse_start: int | None = None
    verse_end: int | None = None
    open_ended: bool = False
    last_verse: bool = False
    from_two_numbers: bool = False
    next_index: int = 0


@cache
def _token_regex(mode: Mode) -> re.Pattern[str]:
    parts = []
    for name, pattern in _TOKEN_SPECS:
        if name == "BOOK":
            pattern = book_regex(mode).pattern
        parts.append(f"(?P<{name}>{pattern})")
    return re.compile("|".join(parts))


def tokenize(text: str, mode: Mode) -> list[Token]:
    tokens = []
    for m in _token_regex(mode).finditer(text):
        kind = m.lastgroup
        raw = m.group(0)
        tok = Token(kind, m.start(), m.end(), raw)
        digits = re.search(r"\d+", raw)
        if kind != "BOOK" and digits:
            tok.value = int(digits.group(0))
            tok.ordinal = kind == "NUM" and raw.endswith("th")
        tokens.append(tok)
    return tokens


class _Reader:
    def __init__(self, norm: Normalized, tokens: list[Token], mode: Mode):
        self.text = norm.text
        self.toks = tokens
        self.mode = mode

    def tok(self, k: int) -> Token | None:
        return self.toks[k] if 0 <= k < len(self.toks) else None

    def adjacent(self, a: int, b: int) -> bool:
        """True if tokens a and b are separated only by spaces, commas or a particle."""
        ta, tb = self.tok(a), self.tok(b)
        if ta is None or tb is None:
            return False
        return bool(_PARTICLE_GAP_RE.fullmatch(self.text[ta.end : tb.start]))

    def is_type(self, k: int, *types: str) -> bool:
        t = self.tok(k)
        return t is not None and t.type in types

    def range_end(self, k: int) -> tuple[int | None, int]:
        """After a verse at k-1: '-18', '부터 18절', 'through 21'."""
        if (
            self.is_type(k, "RANGE")
            and self.adjacent(k - 1, k)
            and self.is_type(k + 1, *_NUMBER_TOKENS)
            and self.adjacent(k, k + 1)
            and not self.toks[k + 1].ordinal
        ):
            return self.toks[k + 1].value, k + 2
        return None, k

    def verse_run(self, k: int, start: int) -> tuple[int | None, int]:
        """Korean verses said in a row become one range.

        k is the token after a 절 token whose verse is start. Consecutive verses
        ("19절 20절", "19절과 20절") extend the range; "1절 5절까지" ends it.
        Out-of-order or skipped verses ("4절 3절", "1절과 4절") stay separate.
        """
        end, current = None, start
        while self.is_type(k, "KO_V") and _LIST_GAP_RE.fullmatch(
            self.text[self.toks[k - 1].end : self.toks[k].start]
        ):
            tok = self.toks[k]
            until = self.text[tok.end :].lstrip().startswith("까지")
            if tok.value == current + 1 or (until and tok.value > current):
                end, current, k = tok.value, tok.value, k + 1
                if until:
                    break
            else:
                break
        return end, k

    def open_marker(self, k: int) -> tuple[bool, int]:
        if self.is_type(k, "OPEN") and self.adjacent(k - 1, k):
            return True, k + 1
        return False, k

    def verse_tail(self, k: int) -> _Spec | None:
        """Verse part after a chapter token at k-1."""
        if not self.adjacent(k - 1, k):
            return None
        t = self.tok(k)
        if t.type in ("KO_V", "EN_V", "EN_V_ORD"):
            end, k2 = self.range_end(k + 1)
            if end is None and t.type == "KO_V":
                end, k2 = self.verse_run(k2, t.value)
            open_ended, k2 = self.open_marker(k2)
            return _Spec(None, t.value, end, open_ended, next_index=k2)
        if (
            t.type == "NUM"
            and not t.ordinal
            and self.is_type(k + 1, "RANGE")
            and self.adjacent(k, k + 1)
            and self.is_type(k + 2, "KO_V")
            and self.adjacent(k + 1, k + 2)
        ):
            return _Spec(None, t.value, self.toks[k + 2].value, next_index=k + 3)
        if t.type == "LAST_V":
            return _Spec(None, last_verse=True, next_index=k + 1)
        return None

    def chapter_spec(self, j: int) -> _Spec | None:
        """Chapter (and verses) starting at token j."""
        t = self.tok(j)
        if t is None:
            return None
        if t.type == "NUM" and not t.ordinal:
            if (
                self.is_type(j + 1, "COLON")
                and self.is_type(j + 2, "NUM")
                and self.text[t.end : self.toks[j + 2].start].strip() == ":"
            ):
                end, k = self.range_end(j + 3)
                open_ended, k = self.open_marker(k)
                return _Spec(t.value, self.toks[j + 2].value, end, open_ended, next_index=k)
            if self.is_type(j + 1, "EN_V") and self.adjacent(j, j + 1):
                end, k = self.range_end(j + 2)
                return _Spec(t.value, self.toks[j + 1].value, end, next_index=k)
            nxt = self.tok(j + 1)
            if nxt and nxt.type == "NUM" and not nxt.ordinal and self.adjacent(j, j + 1):
                end, k = self.range_end(j + 2)
                if end is None:
                    third = self.tok(k)
                    if third and third.type == "NUM" and self.adjacent(k - 1, k):
                        end, k = third.value, k + 1
                return _Spec(t.value, nxt.value, end, from_two_numbers=True, next_index=k)
            return _Spec(t.value, next_index=j + 1)
        if t.type in ("KO_CH", "EN_CH"):
            tail = self.verse_tail(j + 1)
            if tail:
                tail.chapter = t.value
                return tail
            return _Spec(t.value, next_index=j + 1)
        return None


def make_absolute(book: str, spec: _Spec) -> tuple[Reference, float] | None:
    """Validate a book + chapter spec against the versification."""
    chapter, v1, v2 = spec.chapter, spec.verse_start, spec.verse_end
    verses = versification.verse_count(book, chapter)
    if verses is None:
        return None
    if spec.last_verse:
        return Reference(book, chapter, verses), CONF_VERSE
    if v1 is None:
        return Reference(book, chapter), CONF_CHAPTER
    if v1 > verses:
        # "Psalm one nineteen": 1:19 does not exist, 119 does.
        merged = chapter * 100 + v1
        if spec.from_two_numbers and chapter < 10 and v1 < 100 and v2 is None:
            if versification.verse_count(book, merged) is not None:
                return Reference(book, merged), CONF_FALLBACK
        return None
    if v2 is not None:
        v2 = min(v2, verses)
        if v2 <= v1:
            v2 = None
    return Reference(book, chapter, v1, v2, spec.open_ended), CONF_VERSE


def parse(
    norm: Normalized, mode: Mode = "spoken", known_books: frozenset[str] = frozenset()
) -> ParseResult:
    """known_books: books already shown in this service. They allow looser
    near matches for misheard names."""
    text = norm.text
    reader = _Reader(norm, tokenize(text, mode), mode)
    toks = reader.toks
    result = ParseResult(trigger=bool(_TRIGGER_RE.search(text)))
    out = result.mentions
    suppress = False  # inside a hymn mention ("찬송가 305장 3절")
    pending: Token | None = None  # a book name not yet followed by a chapter

    known = set(known_books)

    def emit_abs(
        book: str, spec: _Spec, start: int, end_tok: int, fuzzy_from: str | None = None
    ) -> bool:
        made = make_absolute(book, spec)
        if made is None:
            return False
        ref, conf = made
        if fuzzy_from:
            conf -= FUZZY_PENALTY
        end = toks[end_tok - 1].end
        out.append(RawMention("abs", start, end, ref=ref, confidence=conf, fuzzy_from=fuzzy_from))
        known.add(book)
        return True

    i = 0
    while i < len(toks):
        t = toks[i]
        if t.type == "SENT":
            suppress, pending = False, None
            i += 1
            continue
        if t.type == "HYMN":
            suppress, pending = True, None
            i += 1
            continue
        if t.type == "BOOK":
            suppress = False
            book = lookup(t.text, mode)
            j = i + 1
            if (
                reader.is_type(j, "RANGE")
                and toks[j].text.startswith("에서")
                and reader.adjacent(i, j)
            ):
                j += 1  # "로마서에서 8장"
            spec = reader.chapter_spec(j) if reader.adjacent(i, j) else None
            if book and spec and emit_abs(book, spec, t.start, spec.next_index):
                i, pending = spec.next_index, None
                continue
            pending = t if book else None
            i += 1
            continue
        if t.type == "NAME":
            if not suppress:
                book = fuzzy_lookup(t.text, frozenset(known))
                j = i + 1
                if book and reader.adjacent(i, j):
                    spec = reader.chapter_spec(j)
                    if spec and emit_abs(book, spec, t.start, spec.next_index, fuzzy_from=t.text):
                        i, pending = spec.next_index, None
                        continue
                elif looks_like_book(t.text) and reader.adjacent(i, j):
                    # Probably a misheard book we could not confirm. Do not let the
                    # chapter fall back to the previous book's context.
                    spec = reader.chapter_spec(j)
                    if spec:
                        out.append(RawMention("block", t.start, toks[spec.next_index - 1].end))
                        i, pending = spec.next_index, None
                        continue
            i += 1
            continue
        if suppress:
            i += 1
            continue

        nxt = reader.tok(i + 1)
        # "the 23th psalm", "the 3th chapter of john"
        if (
            nxt is not None
            and nxt.type == "BOOK"
            and reader.adjacent(i, i + 1)
            and ((t.type == "NUM" and t.ordinal) or t.type == "EN_CH_ORD")
        ):
            book = lookup(nxt.text, mode)
            if book and (t.type == "EN_CH_ORD" or book == "ps"):
                if emit_abs(book, _Spec(t.value), t.start, i + 2):
                    i += 2
                    continue

        if t.type in ("KO_CH", "EN_CH"):
            spec = reader.chapter_spec(i)
            near = pending is not None and t.start - pending.end <= _PENDING_BOOK_WINDOW
            if near and emit_abs(lookup(pending.text, mode), spec, pending.start, spec.next_index):
                i, pending = spec.next_index, None
                continue
            out.append(
                RawMention(
                    "chapter",
                    t.start,
                    toks[spec.next_index - 1].end,
                    chapter=spec.chapter,
                    verse_start=spec.verse_start,
                    verse_end=spec.verse_end,
                    open_ended=spec.open_ended,
                    last_verse=spec.last_verse,
                )
            )
            i = spec.next_index
            continue

        if t.type in ("KO_V", "EN_V", "EN_V_ORD"):
            end, k = reader.range_end(i + 1)
            if end is None and t.type == "KO_V":
                end, k = reader.verse_run(k, t.value)
            open_ended, k = reader.open_marker(k)
            out.append(
                RawMention(
                    "verse",
                    t.start,
                    toks[k - 1].end,
                    verse_start=t.value,
                    verse_end=end,
                    open_ended=open_ended,
                )
            )
            i = k
            continue

        if (
            t.type == "NUM"
            and not t.ordinal
            and reader.is_type(i + 1, "RANGE")
            and reader.adjacent(i, i + 1)
            and reader.is_type(i + 2, "KO_V")
            and reader.adjacent(i + 1, i + 2)
        ):
            out.append(
                RawMention(
                    "verse",
                    t.start,
                    toks[i + 2].end,
                    verse_start=t.value,
                    verse_end=toks[i + 2].value,
                )
            )
            i += 3
            continue

        simple = {
            "NEXT_V": "next_verse",
            "PREV_V": "prev_verse",
            "NEXT_CH": "next_chapter",
            "LAST_V": "last_verse",
        }
        if t.type in simple:
            out.append(RawMention(simple[t.type], t.start, t.end))
        i += 1
    return result
