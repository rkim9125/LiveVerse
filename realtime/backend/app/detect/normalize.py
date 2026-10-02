"""Transcript normalization with an offset map back to the original text.

Steps: Unicode NFC, lowercase, unify separators, Korean ordinals (첫 절 -> 1절),
Sino-Korean numbers before 장/편/절, English number words.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.detect.numerals import find_english_numbers, find_korean_numbers

# Range separators: en dash, em dash, figure dash, tildes, wave dash.
_RANGE_CHARS = "–—‒−~～〜∼"
_COLON_CHARS = "："
_KO_ORDINAL_RE = re.compile(r"첫\s*(?:째|번째)?\s*(?=장|절)")
# Speech recognition often hears 시편 as 십편 / "10편": "10편 139편" is Psalm 139.
_PSALM_MISHEARD_RE = re.compile(r"(?<![\d가-힣])10\s*편(?=\s*\d+\s*편)")
_PSALM_ALONE_RE = re.compile(r"(?<![\d가-힣])10\s*편(?!\s*\d)")


@dataclass(frozen=True)
class Normalized:
    original: str
    text: str
    # For each character of text: the original span it came from.
    starts: tuple[int, ...]
    ends: tuple[int, ...]

    def original_span(self, start: int, end: int) -> tuple[int, int]:
        """Map a span of normalized text back to the original text."""
        if end <= start:
            pos = self.starts[start] if start < len(self.starts) else len(self.original)
            return pos, pos
        return self.starts[start], self.ends[end - 1]

    def original_text(self, start: int, end: int) -> str:
        s, e = self.original_span(start, end)
        return self.original[s:e]


def _identity(text: str) -> Normalized:
    n = len(text)
    return Normalized(text, text, tuple(range(n)), tuple(range(1, n + 1)))


def _replace(norm: Normalized, repls: list[tuple[int, int, str]]) -> Normalized:
    """Apply non-overlapping replacements, keeping the offset map."""
    if not repls:
        return norm
    out, starts, ends = [], [], []
    pos = 0
    for s, e, rep in sorted(repls):
        out.append(norm.text[pos:s])
        starts.extend(norm.starts[pos:s])
        ends.extend(norm.ends[pos:s])
        out.append(rep)
        # Every replacement covers at least one character.
        starts.extend([norm.starts[s]] * len(rep))
        ends.extend([norm.ends[e - 1]] * len(rep))
        pos = e
    out.append(norm.text[pos:])
    starts.extend(norm.starts[pos:])
    ends.extend(norm.ends[pos:])
    return Normalized(norm.original, "".join(out), tuple(starts), tuple(ends))


def _per_char(norm: Normalized, fn) -> Normalized:
    repls = []
    for i, ch in enumerate(norm.text):
        new = fn(ch)
        if new != ch:
            repls.append((i, i + 1, new))
    return _replace(norm, repls)


def _map_char(ch: str) -> str:
    if ch in _RANGE_CHARS:
        return "-"
    if ch in _COLON_CHARS:
        return ":"
    return ch.lower()


def normalize(text: str) -> Normalized:
    norm = _identity(unicodedata.normalize("NFC", text))
    norm = _per_char(norm, _map_char)
    norm = _replace(norm, [(m.start(), m.end(), "1") for m in _KO_ORDINAL_RE.finditer(norm.text)])
    norm = _replace(norm, find_korean_numbers(norm.text))
    norm = _replace(norm, find_english_numbers(norm.text))
    norm = _replace(norm, _psalm_fixes(norm.text))
    return norm


def _psalm_fixes(text: str) -> list[tuple[int, int, str]]:
    """'10편 139편' -> '시편 139편'. A lone '10편' (no number after it) is taken as
    the book name 시편 too, unless 시편 was already said ('시편 10편에 보면')."""
    repls = [(m.start(), m.end(), "시편") for m in _PSALM_MISHEARD_RE.finditer(text)]
    for m in _PSALM_ALONE_RE.finditer(text):
        if not text[: m.start()].rstrip().endswith("시편"):
            repls.append((m.start(), m.end(), "시편"))
    return sorted(set(repls))
