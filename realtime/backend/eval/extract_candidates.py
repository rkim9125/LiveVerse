#!/usr/bin/env python3
"""Find Bible reference candidates in Whisper transcripts for human review.

Two nets run over each segment, in time order:
  1. detect(): what the realtime pipeline would show. Context is the last
     reference detected earlier in the sermon, as if the interpreter displayed it.
  2. A loose net: book names, numbers with 장/절/편, "다음 절" and similar,
     hymn words. It catches what detect() misses.

Each candidate gets a type so misses can be counted by cause. Output stays in the
corpus folder (outside the repo):

    $LIVEVERSE_CORPUS/<sermon>/candidates.jsonl   one candidate per line, with a
                                                  "decision" field to fill in
    $LIVEVERSE_CORPUS/<sermon>/review.md          the same list, easier to read
    $LIVEVERSE_CORPUS/candidates-summary.json     counts across sermons

Usage (from realtime/backend):
    uv run python eval/extract_candidates.py sermon-01 sermon-02
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.models import Reference  # noqa: E402
from app.detect.books import book_regex, lookup  # noqa: E402
from app.detect.normalize import normalize  # noqa: E402
from app.detect.pipeline import detect  # noqa: E402

COUNTER_RE = re.compile(r"(\d+|[일이삼사오육칠팔구십백]+)\s*(장|절|편)(?!로|막|기|지|안|짜리)")
WORD_BEFORE_CHAPTER_RE = re.compile(r"([가-힣A-Za-z]{2,})\s*(?:의\s*)?(\d+)\s*장")
RELATIVE_RE = re.compile(r"다음\s*절|앞\s*절|다음\s*장|마지막\s*절|이하|next verse|previous verse")
HYMN_RE = re.compile(r"찬송|hymn", re.I)

# Miss types for net-only candidates.
TYPE_UNKNOWN_NAME = "unknown-book-name"  # "라오디기아 3장 15절"
TYPE_NO_CONTEXT = "relative-without-context"  # "3장 15절" with nothing before it
TYPE_BOOK_ONLY = "book-name-only"  # "룻기에서 보면", no chapter
TYPE_HYMN = "hymn"  # ignored on purpose
TYPE_OTHER_NUMBER = "other-number"  # 장/절 used for something else, or unclear
TYPE_RELATIVE_WORD = "relative-word-unresolved"
# Issues with candidates detect() did find.
ISSUE_CHAPTER_DUP = "chapter-and-verse-duplicate"  # "이사야 40장입니다. 이사야 40장 27절"
ISSUE_VARIANT_DIFF = "prompt-variant-differs"


def corpus_dir() -> Path:
    return Path(os.environ.get("LIVEVERSE_CORPUS", "~/liveverse-corpus")).expanduser()


def load_segments(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        {"start": s["start"], "end": s["end"], "text": s["text"].strip()}
        for s in data["segments"]
        if s["text"].strip()
    ]


def run_detect(segments: list[dict]) -> list[list]:
    """detect() on every segment, carrying the last detection as context."""
    context: Reference | None = None
    out = []
    for seg in segments:
        mentions = detect(seg["text"], context=context)
        out.append(mentions)
        if mentions:
            context = mentions[-1].ref
    return out


def overlapping(segments: list[dict], start: float, end: float) -> list[int]:
    return [i for i, s in enumerate(segments) if s["start"] < end + 1 and s["end"] > start - 1]


def net_hits(text: str) -> list[str]:
    hits = []
    norm = normalize(text).text
    if book_regex("spoken").search(norm):
        hits.append("book")
    if COUNTER_RE.search(text):
        hits.append("counter")
    if RELATIVE_RE.search(text):
        hits.append("relative")
    if HYMN_RE.search(text):
        hits.append("hymn")
    return hits


def classify_miss(text: str, hits: list[str], had_context: bool) -> tuple[str, str]:
    """Return (type, detail) for a segment the loose net caught but detect() did not."""
    if "hymn" in hits:
        return TYPE_HYMN, ""
    for m in WORD_BEFORE_CHAPTER_RE.finditer(text):
        word = m.group(1)
        if lookup(word, "spoken") is None and not re.fullmatch(
            r"(성경|본문|오늘|여기|그|이)", word
        ):
            return TYPE_UNKNOWN_NAME, word
    if "counter" in hits and not had_context:
        return TYPE_NO_CONTEXT, ""
    if "relative" in hits:
        return TYPE_RELATIVE_WORD, ""
    if hits == ["book"]:
        return TYPE_BOOK_ONLY, ""
    return TYPE_OTHER_NUMBER, ""


def chapter_dup(mentions: list) -> bool:
    refs = [m.ref for m in mentions]
    for a in refs:
        for b in refs:
            if (
                a is not b
                and a.verse_start is None
                and b.verse_start is not None
                and (a.book, a.chapter) == (b.book, b.chapter)
            ):
                return True
    return False


def fmt(t: float) -> str:
    m, s = divmod(int(t), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}"


def extract(sermon: str) -> dict:
    d = corpus_dir() / sermon
    plain = load_segments(d / "whisper.json")
    prompted_path = d / "whisper.prompted.json"
    prompted = load_segments(prompted_path) if prompted_path.exists() else []
    plain_det = run_detect(plain)
    prompted_det = run_detect(prompted) if prompted else []

    candidates = []
    seen_prompted: set[int] = set()
    context_seen = False
    for i, seg in enumerate(plain):
        mentions = plain_det[i]
        hits = net_hits(seg["text"])
        if not mentions and not hits:
            continue
        other = overlapping(prompted, seg["start"], seg["end"])
        seen_prompted.update(other)
        other_refs = sorted({str(m.ref) for k in other for m in prompted_det[k]})
        refs = [str(m.ref) for m in mentions]
        cand = {
            "id": f"{sermon}-{len(candidates) + 1:03d}",
            "sermon": sermon,
            "t_start": round(seg["start"], 1),
            "t_end": round(seg["end"], 1),
            "time": fmt(seg["start"]),
            "text": seg["text"],
            "prompted_text": " / ".join(prompted[k]["text"] for k in other),
            "detected": [
                {
                    "ref": str(m.ref),
                    "kind": m.kind,
                    "confidence": m.confidence,
                    "matched": m.matched_text,
                }
                for m in mentions
            ],
            "prompted_detected": other_refs,
            "net": hits,
            "source": "detect" if mentions else "net-only",
            "type": None,
            "detail": "",
            "issues": [],
            "decision": "",  # fill in: accept / fix / reject
            "correct_refs": [],  # fill in when decision is fix
            "notes": "",
        }
        if mentions:
            if chapter_dup(mentions):
                cand["issues"].append(ISSUE_CHAPTER_DUP)
            cand["type"] = "detected-" + (
                "absolute" if mentions[0].kind == "absolute" else "relative"
            )
        else:
            cand["type"], cand["detail"] = classify_miss(seg["text"], hits, context_seen)
        if prompted and sorted(set(refs)) != other_refs:
            cand["issues"].append(ISSUE_VARIANT_DIFF)
        candidates.append(cand)
        context_seen = context_seen or bool(mentions)

    # Detections that only the prompted transcript produced.
    for k, mentions in enumerate(prompted_det):
        if not mentions or k in seen_prompted:
            continue
        seg = prompted[k]
        candidates.append(
            {
                "id": f"{sermon}-{len(candidates) + 1:03d}",
                "sermon": sermon,
                "t_start": round(seg["start"], 1),
                "t_end": round(seg["end"], 1),
                "time": fmt(seg["start"]),
                "text": "",
                "prompted_text": seg["text"],
                "detected": [],
                "prompted_detected": [str(m.ref) for m in mentions],
                "net": [],
                "source": "prompted-only",
                "type": "prompted-only",
                "detail": "",
                "issues": [ISSUE_VARIANT_DIFF],
                "decision": "",
                "correct_refs": [],
                "notes": "",
            }
        )
    candidates.sort(key=lambda c: c["t_start"])

    with (d / "candidates.jsonl").open("w", encoding="utf-8") as f:
        for c in candidates:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    write_review(d / "review.md", sermon, candidates)

    return {
        "sermon": sermon,
        "segments": len(plain),
        "candidates": len(candidates),
        "by_source": dict(Counter(c["source"] for c in candidates)),
        "by_type": dict(Counter(c["type"] for c in candidates)),
        "issues": dict(Counter(i for c in candidates for i in c["issues"])),
        "unknown_names": dict(Counter(c["detail"] for c in candidates if c["detail"])),
    }


def write_review(path: Path, sermon: str, candidates: list[dict]) -> None:
    lines = [
        f"# Review: {sermon}",
        "",
        "Fill in `decision` (accept / fix / reject) and `correct_refs` in candidates.jsonl.",
        "This file is a readable copy.",
        "",
    ]
    for c in candidates:
        det = ", ".join(f"{x['ref']} ({x['kind'][0]}, {x['confidence']})" for x in c["detected"])
        lines.append(
            f"## {c['id']}  [{c['time']}]  {c['type']}"
            + (f" ({c['detail']})" if c["detail"] else "")
        )
        if c["text"]:
            lines.append(f"- text: {c['text']}")
        if c["prompted_text"] and c["prompted_text"] != c["text"]:
            lines.append(f"- prompted: {c['prompted_text']}")
        lines.append(f"- detected: {det or 'none'}")
        if c["prompted_detected"] != [x["ref"] for x in c["detected"]]:
            lines.append(f"- prompted detected: {', '.join(c['prompted_detected']) or 'none'}")
        if c["issues"]:
            lines.append(f"- issues: {', '.join(c['issues'])}")
        lines.append("- decision: [ ] accept  [ ] fix: ____  [ ] reject")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("sermons", nargs="+")
    args = p.parse_args()
    summaries = [extract(s) for s in args.sermons]
    out = corpus_dir() / "candidates-summary.json"
    out.write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
