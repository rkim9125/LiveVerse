"""Spoken number handling for Korean (Sino-Korean) and English.

Both finders return replacements as (start, end, text) so the normalizer can keep
an offset map back to the original transcript.
"""

from __future__ import annotations

import re

# ── Korean ──

SINO_DIGITS = {
    "일": 1,
    "이": 2,
    "삼": 3,
    "사": 4,
    "오": 5,
    "육": 6,
    "륙": 6,
    "칠": 7,
    "팔": 8,
    "구": 9,
}
_DIGIT_TO_SINO = {v: k for k, v in SINO_DIGITS.items() if k != "륙"}

# 일 is never written before 십/백 (십 = 10, 백 = 100).
_SINO_RE = re.compile(
    r"^(?:([이삼사오육륙칠팔구])?(백))?(?:([이삼사오육륙칠팔구])?(십))?([일이삼사오육륙칠팔구])?$"
)


def sino_to_int(s: str) -> int | None:
    """'백십구' -> 119. Returns None if s is not a well-formed Sino-Korean number."""
    m = _SINO_RE.match(s)
    if not s or not m:
        return None
    h_digit, h, t_digit, t, unit = m.groups()
    total = 0
    if h:
        total += 100 * (SINO_DIGITS[h_digit] if h_digit else 1)
    if t:
        total += 10 * (SINO_DIGITS[t_digit] if t_digit else 1)
    if unit:
        total += SINO_DIGITS[unit]
    return total or None


def int_to_sino(n: int) -> str:
    """119 -> '백십구'. Supports 1 to 999."""
    if not 1 <= n <= 999:
        raise ValueError(n)
    h, rest = divmod(n, 100)
    t, u = divmod(rest, 10)
    out = ""
    if h:
        out += ("" if h == 1 else _DIGIT_TO_SINO[h]) + "백"
    if t:
        out += ("" if t == 1 else _DIGIT_TO_SINO[t]) + "십"
    if u:
        out += _DIGIT_TO_SINO[u]
    return out


# A Sino-Korean run directly before a chapter/verse counter. The lookahead skips
# common words that start with a counter syllable (장로, 장막, 절기, 편지, 편안, 3장짜리).
_KO_RUN_RE = re.compile(
    r"(?<![가-힣])([일이삼사오육륙칠팔구십백]+)(\s*)(?=(장|편|절)(?!로|막|기|지|안|짜리))"
)

# Single-syllable numbers glued to a counter that are ordinary words, not references.
_KO_DENY = {"사장", "이장", "구장", "오장", "일장", "구절", "일절", "사절", "이편", "일편"}


def find_korean_numbers(text: str) -> list[tuple[int, int, str]]:
    """Find Sino-Korean numbers used with 장/편/절 and return digit replacements."""
    out = []
    for m in _KO_RUN_RE.finditer(text):
        run, space, counter = m.group(1), m.group(2), m.group(3)
        value = sino_to_int(run)
        if value is None:
            continue
        if len(run) == 1:
            # "이 장", "이 절" usually mean "this chapter / this verse".
            if space and run == "이":
                continue
            if not space and run + counter in _KO_DENY:
                continue
        out.append((m.start(1), m.end(1), str(value)))
    return out


# ── English ──

UNITS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
}
TEENS = {
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
ORD_UNITS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
}
ORD_TEENS = {
    "tenth": 10,
    "eleventh": 11,
    "twelfth": 12,
    "thirteenth": 13,
    "fourteenth": 14,
    "fifteenth": 15,
    "sixteenth": 16,
    "seventeenth": 17,
    "eighteenth": 18,
    "nineteenth": 19,
}
ORD_TENS = {
    "twentieth": 20,
    "thirtieth": 30,
    "fortieth": 40,
    "fiftieth": 50,
    "sixtieth": 60,
    "seventieth": 70,
    "eightieth": 80,
    "ninetieth": 90,
}
_NUMBER_WORDS = (
    set(UNITS)
    | set(TEENS)
    | set(TENS)
    | set(ORD_UNITS)
    | set(ORD_TEENS)
    | set(ORD_TENS)
    | {"hundred", "hundredth"}
)
_RUN_WORDS = _NUMBER_WORDS | {"a", "and"}
_WORD_RE = re.compile(r"[a-z]+")
_SEP_RE = re.compile(r"^[\s-]+$")


def _split_run(words: list[tuple[str, int, int]]) -> list[tuple[int, int, str]]:
    """Split a run of number words into numbers: 'eight twenty eight' -> 8, 28."""
    out = []
    i, n = 0, len(words)

    def w(k: int) -> str | None:
        return words[k][0] if k < n else None

    while i < n:
        start_i, value, ordinal = i, 0, False
        consumed = False
        # hundreds: "one hundred", "a hundred", "hundred"
        if (w(i) in UNITS or w(i) == "a") and w(i + 1) in ("hundred", "hundredth"):
            value = 100 * (1 if w(i) == "a" else UNITS[w(i)])
            ordinal = w(i + 1) == "hundredth"
            i += 2
            consumed = True
        elif w(i) in ("hundred", "hundredth"):
            value, ordinal = 100, w(i) == "hundredth"
            i += 1
            consumed = True
        if consumed and not ordinal and w(i) == "and" and w(i + 1) in _NUMBER_WORDS:
            i += 1
        if not ordinal:
            word = w(i)
            if word in TENS:
                value += TENS[word]
                i += 1
                consumed = True
                if w(i) in UNITS:
                    value += UNITS[w(i)]
                    i += 1
                elif w(i) in ORD_UNITS:
                    value += ORD_UNITS[w(i)]
                    ordinal = True
                    i += 1
            elif word in ORD_TENS:
                value += ORD_TENS[word]
                ordinal, consumed = True, True
                i += 1
            elif word in TEENS or word in UNITS:
                value += TEENS.get(word) or UNITS[word]
                consumed = True
                i += 1
            elif word in ORD_TEENS or word in ORD_UNITS:
                value += ORD_TEENS.get(word) or ORD_UNITS[word]
                ordinal, consumed = True, True
                i += 1
        if not consumed:
            i = start_i + 1  # stray "a" / "and"
            continue
        start, end = words[start_i][1], words[i - 1][2]
        out.append((start, end, f"{value}th" if ordinal else str(value)))
    return out


def find_english_numbers(text: str) -> list[tuple[int, int, str]]:
    """Find English number words (lowercase input) and return digit replacements.

    Ordinals come back with a 'th' suffix ('twenty third' -> '23th') so the parser
    can tell 'the 23th psalm' from a plain number.
    """
    out: list[tuple[int, int, str]] = []
    run: list[tuple[str, int, int]] = []
    prev_end = None
    for m in _WORD_RE.finditer(text):
        word = m.group(0)
        joined = prev_end is not None and _SEP_RE.match(text[prev_end : m.start()] or " ")
        if word in _RUN_WORDS and (not run or joined):
            run.append((word, m.start(), m.end()))
        else:
            if run:
                out.extend(_split_run(run))
            run = [(word, m.start(), m.end())] if word in _RUN_WORDS else []
        prev_end = m.end()
    if run:
        out.extend(_split_run(run))
    return out


def int_to_english(n: int) -> str:
    """119 -> 'one hundred nineteen'. Supports 1 to 999 (used by tests)."""
    if not 1 <= n <= 999:
        raise ValueError(n)
    units = {v: k for k, v in UNITS.items()}
    teens = {v: k for k, v in TEENS.items()}
    tens = {v: k for k, v in TENS.items()}
    h, rest = divmod(n, 100)
    parts = []
    if h:
        parts += [units[h], "hundred"]
    if rest >= 20:
        t, u = divmod(rest, 10)
        parts.append(tens[t * 10])
        if u:
            parts.append(units[u])
    elif rest >= 10:
        parts.append(teens[rest])
    elif rest:
        parts.append(units[rest])
    return " ".join(parts)
