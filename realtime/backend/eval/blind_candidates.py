#!/usr/bin/env python3
"""Build blind review candidates for held-out (test) sermons.

Candidates are the union of three nets over both transcripts (whisper.json and
whisper.prompted.json), merged into time windows:
  - detect(): the frozen detector
  - a loose net: book names, numbers with 장/편/절, relative words, hymn words,
    and unknown words that look like a book name followed by a number
  - quote search with lower thresholds than the detector uses, so fewer quotes
    are missed

Written to $LIVEVERSE_CORPUS/<sermon>/:
  candidates.jsonl        what the reviewer sees: times only, empty labels
  candidates.sources.json which nets produced each window and what detect()
                          found. Not shown during review; read only after labeling.

This script prints counts only, never transcript text, so it can run on a test
set without anyone seeing its content.

Usage (from realtime/backend):
    uv run python eval/blind_candidates.py sermon-03 sermon-04 sermon-05
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extract_candidates import net_hits  # noqa: E402
from score import _mention_time  # noqa: E402

from app.core import bible_text  # noqa: E402
from app.detect.books import looks_like_book  # noqa: E402
from app.detect.normalize import normalize  # noqa: E402
from app.detect.pipeline import detect  # noqa: E402
from app.detect.quotes import QuoteIndex  # noqa: E402

TRANSCRIPTS = ("whisper.json", "whisper.prompted.json")
QUOTE_COVERAGE = 0.3  # the detector uses 0.4
QUOTE_HITS = 8  # the detector uses 10
MAX_WINDOW_S = 45.0
NAME_RE = re.compile(
    r"(?<![가-힣\d])([가-힣]{2,6}?)(?=(?:의|에서|에|을|를|은|는|로)?\s*\d+\s*(?:장|편|:))"
)


def corpus_dir() -> Path:
    return Path(os.environ.get("LIVEVERSE_CORPUS", "~/liveverse-corpus")).expanduser()


def detect_spans(segments: list[dict]) -> list[tuple[float, float, str, str]]:
    context, known = None, set()
    out = []
    for seg in segments:
        words = seg.get("words") or []
        text = "".join(w["word"] for w in words) if words else seg["text"]
        mentions = detect(text, context=context, known_books=known)
        for m in mentions:
            when = _mention_time(words, m.span) if words else None
            start, end = when or (seg["start"], seg["end"])
            out.append((start, end, "detect", str(m.ref)))
            context = m.ref
            known.add(m.ref.book)
    return out


def net_spans(segments: list[dict]) -> list[tuple[float, float, str, str]]:
    out = []
    for seg in segments:
        text = seg["text"]
        near_name = any(looks_like_book(w) for w in NAME_RE.findall(normalize(text).text))
        if net_hits(text) or near_name:
            out.append((seg["start"], seg["end"], "net", ""))
    return out


def quote_spans(segments: list[dict], index: QuoteIndex) -> list[tuple[float, float, str, str]]:
    return [
        (seg["start"], seg["end"], "quote", "")
        for seg in segments
        if index.best_coverage(seg["text"], QUOTE_HITS) >= QUOTE_COVERAGE
    ]


def merge(spans: list[tuple[float, float, str, str]]) -> list[dict]:
    windows: list[dict] = []
    for start, end, source, ref in sorted(spans):
        w = windows[-1] if windows else None
        if w and start < w["t_end"] and max(end, w["t_end"]) - w["t_start"] <= MAX_WINDOW_S:
            w["t_end"] = max(w["t_end"], end)
            w["sources"].add(source)
            if ref:
                w["detected"].add(ref)
        else:
            windows.append(
                {"t_start": start, "t_end": end, "sources": {source}, "detected": {ref} - {""}}
            )
    return windows


def fmt(t: float) -> str:
    m, s = divmod(int(t), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}"


def build(sermon: str, index: QuoteIndex, force: bool) -> dict:
    d = corpus_dir() / sermon
    out_path = d / "candidates.jsonl"
    if out_path.exists() and not force:
        raise SystemExit(f"{out_path} exists; refusing to overwrite labels (use --force)")
    spans = []
    for name in TRANSCRIPTS:
        segments = json.loads((d / name).read_text(encoding="utf-8"))["segments"]
        spans += detect_spans(segments) + net_spans(segments) + quote_spans(segments, index)
    windows = merge(spans)

    rows, sources = [], {}
    for n, w in enumerate(windows, 1):
        wid = f"{sermon}-{n:03d}"
        rows.append(
            {
                "id": wid,
                "sermon": sermon,
                "t_start": round(w["t_start"], 1),
                "t_end": round(w["t_end"], 1),
                "time": fmt(w["t_start"]),
                "blind": True,
                "decision": "",
                "correct_refs": [],
                "label_source": "",
                "review_status": "",
                "notes": "",
            }
        )
        sources[wid] = {"sources": sorted(w["sources"]), "detected": sorted(w["detected"])}
    with out_path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (d / "candidates.sources.json").write_text(json.dumps(sources, indent=1), encoding="utf-8")
    return {
        "sermon": sermon,
        "windows": len(rows),
        "by_source": dict(Counter(s for w in windows for s in w["sources"])),
    }


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("sermons", nargs="+")
    p.add_argument("--force", action="store_true", help="overwrite an existing candidates.jsonl")
    args = p.parse_args()
    index = QuoteIndex(bible_text.load())
    for s in args.sermons:
        print(json.dumps(build(s, index, args.force)))


if __name__ == "__main__":
    main()
