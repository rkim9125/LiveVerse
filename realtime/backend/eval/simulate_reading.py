#!/usr/bin/env python3
"""Simulate reading confirmation (#12) on dev-set transcripts.

After the frozen detector has a spoken position (book, and chapter if known),
each later segment within ANCHOR_S seconds is matched against the Bible text:
  - inside the spoken chapter first (few verses, lenient thresholds)
  - the whole spoken book if no chapter is known (stricter thresholds)
A match is a "reading" of that verse.

For each gold reference, the outcome is counted against what the detector did
in that label window:
  confirm   detector right, reading found the same verse
  right, reading points elsewhere
            detector right, but the reading matched another verse (a replace
            here would make it wrong)
  replace   detector wrong, reading found the gold verse
  recover   detector found nothing, reading found the gold verse
  none      reading did not find the gold verse

Numbers only. Refuses test-set sermons.

Usage (from realtime/backend):
    uv run python eval/simulate_reading.py sermon-01 sermon-02
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import score  # noqa: E402

from app.core import bible_text  # noqa: E402
from app.core.models import Reference  # noqa: E402
from app.detect.announce import dimmed_chapters  # noqa: E402
from app.detect.quotes import _ko_grams  # noqa: E402

ANCHOR_S = 120.0
CHAPTER = {"coverage": 0.3, "hits": 5}
BOOK = {"coverage": 0.5, "hits": 12}
AFTER_LABEL_S = 60.0


def build_grams(text: bible_text.BibleText) -> dict[str, list[list[set[str]]]]:
    return {
        book: [[_ko_grams(v) for v in ko] for ko, _ in chapters]
        for book, chapters in text.books.items()
    }


def best_in(grams: list[tuple[tuple[int, int], set[str]]], seg: set[str], rule: dict):
    best = None
    for key, vg in grams:
        if len(vg) < 6:
            continue
        hits = len(vg & seg)
        cov = hits / len(vg)
        if hits >= rule["hits"] and cov >= rule["coverage"] and (best is None or cov > best[0]):
            best = (cov, key)
    return best


def readings(segments: list[dict], index: dict) -> list[tuple[float, str]]:
    """(time, verse ref) for each segment matched to a verse near the spoken position."""
    dimmed: set[tuple[int, int]] = set()
    for _ in range(2):
        timeline = score._run(segments, dimmed)
        dimmed = dimmed_chapters(timeline)
    timeline = score._run(segments, dimmed)
    out = []
    anchor: tuple[float, Reference] | None = None
    for seg in timeline:
        for m, start, _ in seg.mentions:
            anchor = (start, m.ref)
        if anchor is None or seg.start - anchor[0] > ANCHOR_S:
            continue
        ref = anchor[1]
        chapters = index.get(ref.book)
        if not chapters:
            continue
        seg_grams = _ko_grams(seg.text)
        if 1 <= ref.chapter <= len(chapters):
            pool = [((ref.chapter, v), g) for v, g in enumerate(chapters[ref.chapter - 1], 1)]
            found = best_in(pool, seg_grams, CHAPTER)
        else:
            found = None
        if found is None:
            pool = [((c, v), g) for c, vs in enumerate(chapters, 1) for v, g in enumerate(vs, 1)]
            found = best_in(pool, seg_grams, BOOK)
        if found:
            c, v = found[1]
            out.append((seg.start, f"{ref.book} {c}:{v}"))
    return out


def covers(gold: str, verse: str) -> bool:
    g, r = Reference.parse(gold), Reference.parse(verse)
    if (g.book, g.chapter) != (r.book, r.chapter):
        return False
    if g.verse_start is None:
        return True  # a chapter: any verse of it identifies the passage
    return g.verse_start <= r.verse_start <= (g.verse_end or g.verse_start)


def simulate(sermon: str, transcript: str, index: dict) -> Counter:
    d = score.corpus_dir() / sermon
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    if meta.get("split") != "dev":
        raise SystemExit(f"{sermon} is not a dev sermon")
    segments = json.loads((d / transcript).read_text(encoding="utf-8"))["segments"]
    labels = [json.loads(line) for line in (d / "candidates.jsonl").open(encoding="utf-8")]
    preds = score.predictions(d / transcript)
    reads = readings(segments, index)
    out: Counter = Counter()
    for c in labels:
        if c.get("decision") not in ("accept", "fix") or not c["correct_refs"]:
            continue
        window = [r for a, b, r in preds if c["t_start"] - 1 < b and c["t_end"] + 1 > a]
        later = [r for t, r in reads if c["t_start"] - 1 <= t <= c["t_end"] + AFTER_LABEL_S]
        for gold in c["correct_refs"]:
            found = any(covers(gold, r) for r in later)
            if gold in window:
                if found:
                    out["confirm"] += 1
                elif later:
                    out["right, reading points elsewhere"] += 1  # risk: a wrong replace
                else:
                    out["right, not read"] += 1
            elif window:
                out["replace" if found else "wrong, not read"] += 1
            else:
                out["recover" if found else "missed, not read"] += 1
    return out


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("sermons", nargs="+")
    args = p.parse_args()
    text = bible_text.load()
    if not text.has_korean:
        raise SystemExit("needs local Korean text (data/bible_data.js)")
    index = build_grams(text)
    for transcript in ("whisper.json", "whisper.prompted.json"):
        total: Counter = Counter()
        for s in args.sermons:
            total += simulate(s, transcript, index)
        print(transcript, dict(sorted(total.items())), "gold refs", sum(total.values()))


if __name__ == "__main__":
    main()
