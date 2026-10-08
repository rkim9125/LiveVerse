"""One interpreting session: what the preacher is on, and what the screen shows.

Two kinds of context (design 3.4):
  spoken  the last reference said, including chapters said in passing.
          Relative mentions ("17절", "다음 절") are resolved against it.
          After a book said with a chapter it does not have ("로마서 17장"),
          it is that book alone (spoken_book): "3장" then means 로마서 3장,
          and "2절" means nothing until a chapter is known.
  shown   what is on the interpreter's screen. It changes when a candidate is
          shown at once (display policy) or when the interpreter switches,
          searches or clears.

Display policy (design 3.10): the last showable candidate of a final segment is
shown at once. Showable means confidence at or above the threshold, not dimmed,
not superseded by a verse of the same chapter, and not a repeat of the chapter
already on screen.

Interim display: a verse that is the last showable verse in consecutive interim
segments (interim_repeats), or stays so for interim_hold_s, is shown marked
interim. The next final confirms it (same reference in the final), replaces it
(another pick) or takes it back (neither). Interims never move spoken.

Chapters said in passing (design 3.5): a chapter-only candidate starts dimmed
unless it is confirmed in the same segment. It is promoted if an announcement
phrase or a verse of that chapter arrives within the pending window, and stays
dimmed after that.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field

from app.config import Settings
from app.core.models import Reference
from app.core.store import BibleStore
from app.detect.announce import ANNOUNCE_RE
from app.detect.books import looks_like_book
from app.detect.normalize import normalize
from app.detect.pipeline import analyze
from app.detect.quotes import QuoteIndex
from app.detect.typed import parse_query
from app.llm.base import NullResolver, RefResolver
from app.reading.base import NullReadingTracker, ReadingTracker

_COPULA_RE = re.compile(r"\s*(?:입니다|이에요|예요)")
_NAME_BEFORE_NUMBER = re.compile(
    r"(?<![가-힣\d])([가-힣]{2,6}?)(?=(?:의|에서|에|을|를|은|는|로)?\s*\d+\s*(?:장|편|:))"
)
RECENT_S = 30.0


@dataclass
class Candidate:
    id: str
    ref: Reference
    source: str  # rule, context, quote, llm, manual
    confidence: float
    t: float
    seq: int | None = None
    dimmed: bool = False
    superseded: bool = False
    pending_until: float | None = None
    matched_text: str = ""
    span: tuple[int, int] | None = None  # offsets in the segment text
    fuzzy_from: str | None = None
    guess: bool = False  # in-range guess for out of range numbers; never shown by itself


@dataclass
class Shown:
    candidate: Candidate
    manual: bool = False
    t: float = 0.0
    interim: bool = False  # shown from interim results, not yet confirmed by a final

    @property
    def tentative(self) -> bool:
        return self.candidate.source == "llm"


@dataclass
class Session:
    store: BibleStore
    settings: Settings
    quotes: QuoteIndex | None = None
    reading: ReadingTracker = field(default_factory=NullReadingTracker)
    resolver: RefResolver = field(default_factory=NullResolver)

    def __post_init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.spoken: Reference | None = None
        self.spoken_book: str | None = None
        self.spoken_announced = False
        self._last_book: str | None = None  # from the latest _detect()
        self._watch: Candidate | None = None  # verse being watched in interim results
        self._watch_count = 0
        self._watch_since = 0.0
        self._before_interim: Shown | None = None  # screen before an interim display
        self.shown: Shown | None = None
        self.known_books: set[str] = set()
        self.candidates: deque[Candidate] = deque(maxlen=self.settings.max_candidates)
        self.recent: deque[tuple[float, str]] = deque()
        self.history: list[dict] = []
        self._next_id = 0
        self.reading.reset()

    # ── detection ──

    def _new_id(self) -> str:
        self._next_id += 1
        return f"c{self._next_id}"

    def _detect(self, text: str, seq: int | None, now: float) -> list[Candidate]:
        found = analyze(
            text, context=self.spoken, context_book=self.spoken_book, known_books=self.known_books
        )
        self._last_book = found.book
        cands = [
            Candidate(
                id=self._new_id(),
                ref=m.ref,
                source="rule" if m.kind == "absolute" else "context",
                confidence=m.confidence,
                t=now,
                seq=seq,
                superseded=m.superseded,
                matched_text=m.matched_text,
                span=m.span,
                fuzzy_from=m.fuzzy_from,
            )
            for m in found.mentions
        ]
        cands += [
            Candidate(
                id=self._new_id(),
                ref=m.ref,
                source="rule",
                confidence=m.confidence,
                t=now,
                seq=seq,
                matched_text=m.matched_text,
                span=m.span,
                guess=True,
            )
            for m in found.guesses
            if all(c.ref != m.ref for c in cands)
        ]
        if self.quotes is not None:
            quoted = self.quotes.find(text, spoken=self.spoken, announced=self.spoken_announced)
            if quoted and all(c.ref != quoted.ref for c in cands):
                cands.append(
                    Candidate(self._new_id(), quoted.ref, "quote", quoted.confidence, now, seq)
                )
        return cands

    def preview(self, text: str, now: float) -> list[dict]:
        """Candidates in an interim segment. Changes nothing."""
        saved = self._next_id
        cands = self._detect(text, None, now)
        self._next_id = saved
        return [self._candidate_view(c) for c in cands]

    # ── interim display ──

    def _end_watch(self) -> None:
        self._watch, self._watch_count = None, 0

    def process_interim(self, text: str, now: float, seq: int | None = None) -> bool:
        """Watch an interim segment for a stable verse. Returns True if the
        screen changed. Spoken, candidates and alternatives are not touched."""
        if not self.settings.interim_show:
            return False
        saved = self._next_id, self._last_book
        cands = self._detect(text, seq, now)
        self._next_id, self._last_book = saved
        verses = [
            c
            for c in cands
            if c.ref.verse_start is not None
            and c.source in ("rule", "context")
            and not c.guess
            and not c.superseded
            and c.confidence >= self.settings.show_threshold
        ]
        if not verses:
            self._end_watch()
            return False
        last = verses[-1]
        if self._watch is not None and self._watch.ref == last.ref:
            self._watch_count += 1
        else:
            self._watch, self._watch_count, self._watch_since = last, 1, now
        return self.tick(now)

    def interim_due(self) -> float | None:
        """When the watched verse will have been held long enough, if it is not
        shown yet: the caller can call tick() then."""
        if self._watch is None or self._watched_is_shown():
            return None
        return self._watch_since + self.settings.interim_hold_s

    def _watched_is_shown(self) -> bool:
        return self.shown is not None and self.shown.candidate.ref == self._watch.ref

    def tick(self, now: float) -> bool:
        """Show the watched verse if it is stable. Returns True if shown."""
        w = self._watch
        if w is None or self._watched_is_shown():
            return False
        stable = (
            self._watch_count >= self.settings.interim_repeats
            or now - self._watch_since
            >= self.settings.interim_hold_s - 1e-3  # float error at epoch times
        )
        if not stable:
            return False
        if self.shown is None or not self.shown.interim:
            self._before_interim = self.shown
        self.shown = Shown(w, manual=False, t=now, interim=True)
        self.history.append({"t": now, "ref": str(w.ref), "source": w.source, "reason": "interim"})
        return True

    def _settle_interim(self, cands: list[Candidate], pick: Candidate | None, now: float) -> bool:
        """A final arrived while an interim display is on screen."""
        shown = self.shown
        same = next((c for c in cands if not c.guess and c.ref == shown.candidate.ref), None)
        if pick is not None and pick.ref != shown.candidate.ref:
            return self._show(pick, now, manual=False, reason="mention")
        if same is not None:
            self.shown = Shown(same, manual=False, t=now)
            self.history.append(
                {"t": now, "ref": str(same.ref), "source": same.source, "reason": "confirm"}
            )
            return True
        self.shown = self._before_interim
        ref = str(self.shown.candidate.ref) if self.shown else None
        self.history.append({"t": now, "ref": ref, "source": None, "reason": "revert"})
        return True

    # ── chapters said in passing ──

    def _announced_recently(self, now: float) -> bool:
        return any(
            ANNOUNCE_RE.search(t) for at, t in self.recent if now - at <= self.settings.pending_s
        )

    def _gate_chapters(self, cands: list[Candidate], text: str, now: float) -> None:
        for c in cands:
            if c.ref.verse_start is not None or c.source == "quote" or c.superseded or c.guess:
                continue
            copula = c.span is not None and _COPULA_RE.match(text[c.span[1] :])
            if copula or self._announced_recently(now):
                continue
            c.dimmed = True
            c.pending_until = now + self.settings.pending_s

    def _promote_pending(self, text: str, cands: list[Candidate], now: float) -> list[Candidate]:
        promoted = []
        announced = bool(ANNOUNCE_RE.search(text))
        for c in self.candidates:
            if not c.dimmed or c.pending_until is None:
                continue
            if now > c.pending_until:
                c.pending_until = None  # stays dimmed
                continue
            verse_of_it = any(
                not n.guess
                and n.ref.verse_start is not None
                and (n.ref.book, n.ref.chapter) == (c.ref.book, c.ref.chapter)
                for n in cands
            )
            if announced or verse_of_it:
                c.dimmed, c.pending_until = False, None
                promoted.append(c)
        return promoted

    # ── LLM hook ──

    def _ambiguous(self, text: str) -> bool:
        """An unknown word that looks like a book name, right before a chapter number."""
        return any(looks_like_book(w) for w in _NAME_BEFORE_NUMBER.findall(normalize(text).text))

    # ── display policy ──

    def _repeats_shown(self, c: Candidate) -> bool:
        if self.shown is None:
            return False
        s = self.shown.candidate.ref
        return (
            s.verse_start is not None
            and c.ref.verse_start is None
            and (s.book, s.chapter) == (c.ref.book, c.ref.chapter)
        )

    def _showable(self, c: Candidate) -> bool:
        return (
            not c.dimmed
            and not c.guess
            and not c.superseded
            and c.confidence >= self.settings.show_threshold
            and not self._repeats_shown(c)
        )

    def _show(self, c: Candidate, now: float, manual: bool, reason: str) -> bool:
        same = self.shown and self.shown.candidate.ref == c.ref and self.shown.manual == manual
        if same and not self.shown.interim:
            return False
        self._before_interim = None
        self.shown = Shown(c, manual=manual, t=now)
        self.known_books.add(c.ref.book)
        self.history.append({"t": now, "ref": str(c.ref), "source": c.source, "reason": reason})
        return True

    # ── events ──

    def process_final(self, text: str, now: float, seq: int | None = None) -> bool:
        """Handle a final transcript segment. Returns True if the state changed."""
        cands = self._detect(text, seq, now)
        self.recent.append((now, text))
        while self.recent and now - self.recent[0][0] > RECENT_S:
            self.recent.popleft()
        self._gate_chapters(cands, text, now)
        promoted = self._promote_pending(text, cands, now)

        if not cands and self._ambiguous(text):
            for g in self.resolver.resolve(text, self.spoken):
                cands.append(Candidate(self._new_id(), g.ref, "llm", g.confidence, now, seq))

        said = [c for c in cands if not c.guess]
        if self._last_book is not None and not any(c.source == "quote" for c in said):
            self.spoken, self.spoken_book, self.spoken_announced = None, self._last_book, False
        elif said:
            self.spoken, self.spoken_book = said[-1].ref, None
            self.spoken_announced = not said[-1].dimmed
        for c in cands:
            self.candidates.appendleft(c)

        shown_ref = self.shown.candidate.ref if self.shown else None
        self.reading.observe(text, now, self.spoken, shown_ref)

        changed = bool(cands or promoted)
        pick = next((c for c in reversed(cands) if self._showable(c)), None)
        pick = pick or next((c for c in reversed(promoted) if self._showable(c)), None)
        self._end_watch()
        if self.shown is not None and self.shown.interim:
            return self._settle_interim(cands, pick, now) or changed
        if pick is not None:
            changed = self._show(pick, now, manual=False, reason="mention") or changed
        return changed

    def switch(self, candidate_id: str, now: float) -> bool:
        c = next((c for c in self.candidates if c.id == candidate_id), None)
        if c is None:
            raise KeyError(candidate_id)
        self._end_watch()
        return self._show(c, now, manual=True, reason="switch")

    def search(self, query: str, now: float) -> bool:
        ref = parse_query(query)
        self._end_watch()
        c = Candidate(self._new_id(), ref, "manual", 1.0, now)
        self.candidates.appendleft(c)
        self.spoken, self.spoken_book, self.spoken_announced = ref, None, True
        return self._show(c, now, manual=True, reason="search")

    def clear(self, now: float) -> bool:
        self._end_watch()
        self._before_interim = None
        if self.shown is None:
            return False
        self.shown = None
        self.history.append({"t": now, "ref": None, "source": None, "reason": "clear"})
        return True

    # ── views ──

    def _candidate_view(self, c: Candidate) -> dict:
        return {
            "id": c.id,
            "ref": str(c.ref),
            "label": self.store.label(c.ref),
            "source": c.source,
            "confidence": round(c.confidence, 2),
            "dimmed": c.dimmed,
            "fuzzy_from": c.fuzzy_from,
            "guess": c.guess,
        }

    def state(self) -> dict:
        shown = None
        if self.shown is not None:
            c = self.shown.candidate
            try:
                verses = [v.__dict__ for v in self.store.verses(c.ref)]
            except KeyError:
                verses = []
            shown = self._candidate_view(c) | {
                "tentative": self.shown.tentative,
                "manual": self.shown.manual,
                "interim": self.shown.interim,
                "verses": verses,
            }
        seen = {shown["ref"]} if shown else set()
        alternatives = []
        for c in self.candidates:
            if c.superseded or str(c.ref) in seen:
                continue
            seen.add(str(c.ref))
            alternatives.append(self._candidate_view(c))
            if len(alternatives) == self.settings.max_alternatives:
                break
        reading = self.reading.current()
        return {
            "type": "state",
            "shown": shown,
            "alternatives": alternatives,
            "spoken": (
                {"ref": str(self.spoken)}
                if self.spoken
                else {"ref": None, "book": self.spoken_book}
                if self.spoken_book
                else None
            ),
            "reading": (
                {
                    "ref": str(reading.ref),
                    "outcome": reading.outcome,
                    "confidence": reading.confidence,
                }
                if reading
                else None
            ),
            "names": self.store.names,
        }
