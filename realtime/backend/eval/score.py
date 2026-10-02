#!/usr/bin/env python3
"""Score detect() on a sermon transcript against reviewed candidate labels.

Labels come from $LIVEVERSE_CORPUS/<sermon>/candidates.jsonl (decision and
correct_refs). Each labeled candidate is a time window. detect() runs over the
chosen transcript in order, carrying the last detection as context, and every
detection is matched to the label windows it overlaps:

    TP  detected ref that is in the window's correct_refs
    FP  detected ref that is not, or a detection outside every labeled window
    FN  correct ref that was not detected in its window

Matching by time, not by segment index, keeps scores comparable after the audio
is transcribed again with different settings.

The report holds numbers only, never transcript text.

Usage (from realtime/backend):
    uv run python eval/score.py sermon-01 sermon-02 --name baseline
    uv run python eval/score.py sermon-01 sermon-02 --transcript whisper.prompted.json \
        --name prompt-fix
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.detect.announce import TimedSegment, dimmed_chapters  # noqa: E402
from app.detect.pipeline import detect  # noqa: E402

SLACK_S = 1.0  # seconds of tolerance when matching a detection to a label window
# "dedup" scoring: a missed ref still counts as found if the same ref was detected
# within this many seconds. detect() reports a repeated mention once, which is what
# the interpreter wants, but strict scoring counts the repeat as a miss.
DEDUP_S = 15.0


def corpus_dir() -> Path:
    return Path(os.environ.get("LIVEVERSE_CORPUS", "~/liveverse-corpus")).expanduser()


def _mention_time(words: list[dict], span: tuple[int, int]) -> tuple[float, float] | None:
    """Time of a mention from the words its character span covers."""
    pos, start, end = 0, None, None
    for w in words:
        w_start, w_end = pos, pos + len(w["word"])
        if w_end > span[0] and w_start < span[1]:
            start = w["start"] if start is None else start
            end = w["end"]
        pos = w_end
    return (start, end) if start is not None else None


SUPERSEDED: Counter[str] = Counter()  # chapter candidates hidden behind a verse, per file
DIMMED: Counter[str] = Counter()  # chapter candidates said in passing, per file


def predictions(transcript: Path) -> list[tuple[float, float, str]]:
    """Detections with the time of the words they matched.

    Segments can be up to 30 s long, so the segment time alone could match a
    detection to the wrong label window. Word timestamps place it exactly.
    """
    segments = json.loads(transcript.read_text(encoding="utf-8"))["segments"]
    # Dimmed chapters depend on what is said after them, and the context depends
    # on which candidates were shown. Two passes settle both.
    dimmed: set[tuple[int, int]] = set()
    for _ in range(2):
        timeline = _run(segments, dimmed)
        dimmed = dimmed_chapters(timeline)
    timeline = _run(segments, dimmed)
    dimmed = dimmed_chapters(timeline)
    SUPERSEDED[str(transcript)] = sum(m.superseded for s in timeline for m, _, _ in s.mentions)
    DIMMED[str(transcript)] = len(dimmed)
    return [
        (start, end, str(m.ref))
        for i, s in enumerate(timeline)
        for j, (m, start, end) in enumerate(s.mentions)
        if (i, j) not in dimmed
    ]


def _run(segments: list[dict], dimmed: set[tuple[int, int]]) -> list[TimedSegment]:
    """detect() over the transcript.

    Relative references ("2절") follow where the preacher is: the last reference
    said, dimmed or not ("이제 2장에 보면" moves back to chapter 2 even though it is
    not worth displaying). Books count as shown only for candidates that were not
    dimmed, as if the interpreter clicked each of those."""
    context = None
    known_books: set[str] = set()
    timeline = []
    for i, seg in enumerate(segments):
        words = seg.get("words") or []
        text = "".join(w["word"] for w in words) if words else seg["text"]
        mentions = detect(text, context=context, known_books=known_books)
        timed = TimedSegment(seg["start"], seg["end"], text)
        for j, m in enumerate(mentions):
            when = _mention_time(words, m.span) if words else None
            start, end = when or (seg["start"], seg["end"])
            timed.mentions.append((m, start, end))
            context = m.ref
            if (i, j) not in dimmed:
                known_books.add(m.ref.book)
        timeline.append(timed)
    return timeline


def score_sermon(sermon: str, transcript_name: str) -> dict:
    d = corpus_dir() / sermon
    labels = [json.loads(line) for line in (d / "candidates.jsonl").open(encoding="utf-8")]
    labels = [c for c in labels if c.get("decision") in ("accept", "fix", "reject")]
    preds = predictions(d / transcript_name)
    meta_path = d / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    window_preds: dict[str, set[str]] = {c["id"]: set() for c in labels}
    unlabeled_fp = 0
    for start, end, ref in preds:
        hit = [c for c in labels if c["t_start"] - SLACK_S < end and c["t_end"] + SLACK_S > start]
        if not hit:
            unlabeled_fp += 1
            continue
        # A detection counts once, in the window whose labels contain it if any.
        best = next((c for c in hit if ref in c["correct_refs"]), hit[0])
        window_preds[best["id"]].add(ref)

    tp = fp = fn = dedup_hits = 0
    fn_types: Counter[str] = Counter()
    fp_types: Counter[str] = Counter()
    for c in labels:
        gold = set(c["correct_refs"])
        pred = window_preds[c["id"]]
        c_tp, c_fp, c_fn = len(gold & pred), len(pred - gold), len(gold - pred)
        tp, fp, fn = tp + c_tp, fp + c_fp, fn + c_fn
        for ref in gold - pred:
            if any(
                r == ref and c["t_start"] - DEDUP_S <= a <= c["t_end"] + DEDUP_S
                for a, _, r in preds
            ):
                dedup_hits += 1
        for t in c.get("error_types", []):
            if c_fn:
                fn_types[t] += c_fn
            if c_fp:
                fp_types[t] += c_fp
    fp += unlabeled_fp
    return {
        "split": meta.get("split", "unset"),
        "agreement": agreement(labels),
        "sermon": sermon,
        "labels": len(labels),
        "label_sources": dict(Counter(c.get("label_source", "?") for c in labels)),
        "gold_refs": sum(len(c["correct_refs"]) for c in labels),
        "detections": len(preds),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "unlabeled_fp": unlabeled_fp,
        "dedup_hits": dedup_hits,
        "superseded": SUPERSEDED[str(d / transcript_name)],
        "dimmed": DIMMED[str(d / transcript_name)],
        "fp_by_type": dict(fp_types),
        "fn_by_type": dict(fn_types),
    }


def agreement(labels: list[dict]) -> dict:
    """How often the first-pass AI label (claude_refs) matched the final label."""
    rows = [c for c in labels if "claude_refs" in c]
    same = sum(sorted(c["claude_refs"]) == sorted(c["correct_refs"]) for c in rows)
    ai = sum(len(c["claude_refs"]) for c in rows)
    human = sum(len(c["correct_refs"]) for c in rows)
    both = sum(len(set(c["claude_refs"]) & set(c["correct_refs"])) for c in rows)
    return {"windows": len(rows), "same": same, "ai_refs": ai, "human_refs": human, "both": both}


def agreement_rates(a: dict) -> dict:
    return {
        "window_rate": round(a["same"] / a["windows"], 3) if a["windows"] else 0.0,
        "ai_ref_precision": round(a["both"] / a["ai_refs"], 3) if a["ai_refs"] else 0.0,
        "ai_ref_recall": round(a["both"] / a["human_refs"], 3) if a["human_refs"] else 0.0,
    }


def metrics(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(f1, 3)}


def git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True
        )
        return out.stdout.strip()
    except OSError:
        return "?"


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("sermons", nargs="+")
    p.add_argument("--transcript", default="whisper.json")
    p.add_argument("--name", required=True, help="report name, e.g. baseline")
    args = p.parse_args()

    per = [score_sermon(s, args.transcript) for s in args.sermons]
    keys = (
        "labels",
        "gold_refs",
        "detections",
        "tp",
        "fp",
        "fn",
        "unlabeled_fp",
        "dedup_hits",
        "superseded",
        "dimmed",
    )
    total = {k: sum(s[k] for s in per) for k in keys}
    for s in per + [total]:
        s["strict"] = metrics(s["tp"], s["fp"], s["fn"])
        s["dedup"] = metrics(s["tp"] + s["dedup_hits"], s["fp"], s["fn"] - s["dedup_hits"])
    total["label_sources"] = dict(sum((Counter(s["label_sources"]) for s in per), Counter()))
    total["agreement"] = dict(sum((Counter(s["agreement"]) for s in per), Counter()))
    for s in per + [total]:
        s["agreement"].update(agreement_rates(s["agreement"]))
    total["fp_by_type"] = dict(sum((Counter(s["fp_by_type"]) for s in per), Counter()))
    total["fn_by_type"] = dict(sum((Counter(s["fn_by_type"]) for s in per), Counter()))

    splits = sorted({s["split"] for s in per})
    if len(splits) > 1:
        raise SystemExit(f"do not mix dev and test sermons in one report: {splits}")
    report = {
        "name": args.name,
        "split": splits[0],
        "at": datetime.now().isoformat(timespec="seconds"),
        "git_commit": git_commit(),
        "transcript": args.transcript,
        "total": total,
        "per_sermon": per,
    }
    out_dir = corpus_dir() / "reports"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{args.name}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    out.with_suffix(".md").write_text(markdown(report), encoding="utf-8")
    print(markdown(report))
    print(f"wrote {out} and {out.with_suffix('.md').name}")


def markdown(report: dict) -> str:
    t = report["total"]
    sources = ", ".join(f"{k} {v}" for k, v in t["label_sources"].items())
    lines = [
        f"# Score: {report['name']} ({report['split']} set)",
        "",
        f"- Date: {report['at'][:10]}, code git {report['git_commit']}",
        f"- Transcript: {report['transcript']}",
        f"- Labels: {t['labels']} windows ({sources}), {t['gold_refs']} gold refs",
        f"- Dedup: a repeated ref detected within {DEDUP_S:.0f} s counts as found",
        f"- Chapter candidates hidden behind a verse of the same chapter: {t['superseded']}"
        " (still scored, per LABELING.md)",
        f"- Chapter candidates dimmed as said in passing (not counted): {t['dimmed']}",
        "",
        "## Detection",
        "",
        "| | detections | TP | FP | FN | precision | recall | F1 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    rows = [("total", t)] + [(s["sermon"], s) for s in report["per_sermon"]]
    for name, s in rows:
        for kind in ("strict", "dedup"):
            m = s[kind]
            hits = s["dedup_hits"] if kind == "dedup" else 0
            lines.append(
                f"| {name} {kind} | {s['detections']} | {s['tp'] + hits} | {s['fp']} "
                f"| {s['fn'] - hits} | {m['precision']} | {m['recall']} | {m['f1']} |"
            )
    lines += [
        "",
        "## First-pass AI labels vs final human labels",
        "",
        "| | windows | same label | window agreement | AI ref precision | AI ref recall |",
        "|---|---|---|---|---|---|",
    ]
    for name, s in rows:
        a = s["agreement"]
        lines.append(
            f"| {name} | {a['windows']} | {a['same']} | {a['window_rate']} "
            f"| {a['ai_ref_precision']} | {a['ai_ref_recall']} |"
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
