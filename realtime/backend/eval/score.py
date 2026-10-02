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
from app.detect.pipeline import detect  # noqa: E402

SLACK_S = 1.0  # seconds of tolerance when matching a detection to a label window


def corpus_dir() -> Path:
    return Path(os.environ.get("LIVEVERSE_CORPUS", "~/liveverse-corpus")).expanduser()


def predictions(transcript: Path) -> list[tuple[float, float, str]]:
    segments = json.loads(transcript.read_text(encoding="utf-8"))["segments"]
    context = None
    out = []
    for seg in segments:
        mentions = detect(seg["text"], context=context)
        for m in mentions:
            out.append((seg["start"], seg["end"], str(m.ref)))
        if mentions:
            context = mentions[-1].ref
    return out


def score_sermon(sermon: str, transcript_name: str) -> dict:
    d = corpus_dir() / sermon
    labels = [json.loads(line) for line in (d / "candidates.jsonl").open(encoding="utf-8")]
    labels = [c for c in labels if c.get("decision") in ("accept", "fix", "reject")]
    preds = predictions(d / transcript_name)

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

    tp = fp = fn = 0
    fn_types: Counter[str] = Counter()
    fp_types: Counter[str] = Counter()
    for c in labels:
        gold = set(c["correct_refs"])
        pred = window_preds[c["id"]]
        c_tp, c_fp, c_fn = len(gold & pred), len(pred - gold), len(gold - pred)
        tp, fp, fn = tp + c_tp, fp + c_fp, fn + c_fn
        for t in c.get("error_types", []):
            if c_fn:
                fn_types[t] += c_fn
            if c_fp:
                fp_types[t] += c_fp
    fp += unlabeled_fp
    return {
        "sermon": sermon,
        "labels": len(labels),
        "label_sources": dict(Counter(c.get("label_source", "?") for c in labels)),
        "gold_refs": sum(len(c["correct_refs"]) for c in labels),
        "detections": len(preds),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "unlabeled_fp": unlabeled_fp,
        "fp_by_type": dict(fp_types),
        "fn_by_type": dict(fn_types),
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
    for s in per:
        s.update(metrics(s["tp"], s["fp"], s["fn"]))
    total = {
        k: sum(s[k] for s in per)
        for k in ("labels", "gold_refs", "detections", "tp", "fp", "fn", "unlabeled_fp")
    }
    total.update(metrics(total["tp"], total["fp"], total["fn"]))
    total["fp_by_type"] = dict(sum((Counter(s["fp_by_type"]) for s in per), Counter()))
    total["fn_by_type"] = dict(sum((Counter(s["fn_by_type"]) for s in per), Counter()))

    report = {
        "name": args.name,
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
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
