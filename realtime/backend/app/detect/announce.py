"""Tell announced chapters from chapters mentioned in passing.

Preachers announce a passage to open ("룻기 2장을 보시겠습니다") but also name
chapters while retelling a story ("2장에 보면 ... 볼 수 있습니다"). Only the first
is something the interpreter wants to display.

A chapter-only candidate is confirmed when, within WINDOW_S seconds on either side:
  - an announcement phrase is said (보시겠습니다, 펴, 같이 읽겠습니다, ...), or
  - a verse of the same chapter is said after it, or
  - the chapter itself is followed by 입니다 ("이사야 40장입니다").
Otherwise it is dimmed: still shown, faintly, and not counted as a detection.

This needs speech after the mention, so a live session shows a chapter dimmed
first and confirms it when the announcement or verse arrives.

The phrase list and the window were tuned on the dev set (sermon-01, sermon-02).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.models import Mention

WINDOW_S = 10.0

ANNOUNCE_RE = re.compile(
    r"보시겠|봐\s*볼까|보실까|봅시다|볼까요|펴|펼|찾으셨|찾아\s*보|읽겠|읽어\s*볼까|읽읍시다"
    r"|돌아가\s*(?:보|겠)|넘어가|함께\s*보|같이\s*보"
    r"|let'?s\s+(?:turn|read|look)|turn\s+(?:with\s+me\s+)?to|open\s+your\s+bibles?",
    re.IGNORECASE,
)
_COPULA_RE = re.compile(r"\s*(?:입니다|이에요|예요)")


@dataclass
class TimedSegment:
    start: float
    end: float
    text: str
    # (mention, start time, end time) for each mention in the segment
    mentions: list[tuple[Mention, float, float]] = field(default_factory=list)


def _confirmed(m: Mention, m_start: float, m_end: float, seg: TimedSegment, timeline) -> bool:
    if _COPULA_RE.match(seg.text[m.span[1] :]):
        return True
    for other in timeline:
        if other.start > m_end + WINDOW_S or other.end < m_start - WINDOW_S:
            continue
        if ANNOUNCE_RE.search(other.text):
            return True
        for n, n_start, _ in other.mentions:
            if (
                n_start >= m_start
                and n_start <= m_end + WINDOW_S
                and n.ref.book == m.ref.book
                and n.ref.chapter == m.ref.chapter
                and n.ref.verse_start is not None
            ):
                return True
    return False


def dimmed_chapters(timeline: list[TimedSegment]) -> set[tuple[int, int]]:
    """(segment index, mention index) of chapter-only mentions said in passing."""
    out = set()
    for i, seg in enumerate(timeline):
        for j, (m, m_start, m_end) in enumerate(seg.mentions):
            if m.ref.verse_start is None and not _confirmed(m, m_start, m_end, seg, timeline):
                out.add((i, j))
    return out
