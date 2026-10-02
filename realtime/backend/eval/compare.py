#!/usr/bin/env python3
"""Build one comparison table from score.py reports.

Each row is a step. Each step has two reports: <step>.noprompt and <step>.prompt
(scored on whisper.json and whisper.prompted.json).

Usage (from realtime/backend):
    uv run python eval/compare.py --out comparison-dev.md start 1-fuzzy-names 2-no-context
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def corpus_dir() -> Path:
    return Path(os.environ.get("LIVEVERSE_CORPUS", "~/liveverse-corpus")).expanduser()


def cell(report: dict, kind: str) -> str:
    return str(report["total"][kind]["f1"])


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("steps", nargs="+")
    p.add_argument("--out", required=True)
    args = p.parse_args()

    reports_dir = corpus_dir() / "reports"
    rows, splits, commits = [], set(), []
    for step in args.steps:
        pair = {}
        for variant in ("noprompt", "prompt"):
            path = reports_dir / f"{step}.{variant}.json"
            pair[variant] = json.loads(path.read_text(encoding="utf-8"))
            splits.add(pair[variant]["split"])
        commits.append(pair["prompt"]["git_commit"])
        rows.append((step, pair))
    if len(splits) > 1:
        raise SystemExit(f"steps mix sets: {splits}")
    split = splits.pop()

    first = rows[0][1]["prompt"]["total"]
    lines = [
        f"# Comparison ({split} set)",
        "",
        f"- Set: **{split}**. "
        + (
            "Rule thresholds were tuned on this set, so these numbers are optimistic."
            if split == "dev"
            else "Held out: never used to build rules."
        ),
        f"- Labels: {first['labels']} windows, {first['gold_refs']} gold refs",
        "- F1 shown; strict = every labeled mention, dedup = a repeat within 15 s counts as found",
        "",
        "| step | commit | no prompt strict | no prompt dedup "
        "| prompt strict | prompt dedup | prompt P / R (strict) |",
        "|---|---|---|---|---|---|---|",
    ]
    for (step, pair), commit in zip(rows, commits, strict=True):
        n, pr = pair["noprompt"], pair["prompt"]
        st = pr["total"]["strict"]
        lines.append(
            f"| {step} | {commit} | {cell(n, 'strict')} | {cell(n, 'dedup')} "
            f"| {cell(pr, 'strict')} | {cell(pr, 'dedup')} | {st['precision']} / {st['recall']} |"
        )
    out = reports_dir / args.out
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
