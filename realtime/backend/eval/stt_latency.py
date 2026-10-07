#!/usr/bin/env python3
"""Latency from the end of a spoken reference to the screen, for one replay.

For each gold reference in the played clip, the speech end is the label's end
time (from Whisper word timestamps), put on the wall clock with the run file:

    speech_end = t0 + (t_end - clip_start)

The first segment in the latency log after that moment which changed the screen
to that reference gives the server times, and its rendered event gives the
screen time. Each hop is reported as p50 / p95 / max in milliseconds:

    stt        speech end to the client sending the final segment
    server     server receive to state sent
    render     state sent to drawn on screen
    total      speech end to drawn on screen

References that never reached the screen within the wait are counted as missed.

Usage (from realtime/backend):
    uv run python eval/stt_latency.py ~/liveverse-corpus/sermon-01/runs/20261008-201500.json \\
        logs/latency-20261008.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

WAIT_S = 30.0  # a reference shown later than this after it was said is not matched


def corpus_dir() -> Path:
    return Path(os.environ.get("LIVEVERSE_CORPUS", "~/liveverse-corpus")).expanduser()


def _stats(values: list[float]) -> dict | None:
    if not values:
        return None
    v = sorted(values)

    def at(q: float) -> float:
        return v[min(len(v) - 1, int(round(q * (len(v) - 1))))]

    return {
        "n": len(v),
        "p50_ms": round(at(0.5) * 1000),
        "p95_ms": round(at(0.95) * 1000),
        "max_ms": round(v[-1] * 1000),
    }


def measure(labels: list[dict], run: dict, records: list[dict], wait: float = WAIT_S) -> dict:
    t0, clip = run["t0"], run["clip_start"]
    clip_end = clip + run.get("duration", float("inf"))
    gold = sorted(
        (c for c in labels if c.get("correct_refs") and clip <= c["t_end"] <= clip_end),
        key=lambda c: c["t_end"],
    )
    sent = sorted(
        (r for r in records if r.get("event") == "segment" and r.get("t_sent") and r.get("shown")),
        key=lambda r: r["t_sent"],
    )
    rendered = {
        (r["conn"], r["seq"]): r
        for r in records
        if r.get("event") == "rendered" and r.get("t_render") is not None
    }
    hops: dict[str, list[float]] = {"stt": [], "server": [], "render": [], "total": []}
    missed = 0
    used: set[tuple[str, int]] = set()
    for c in gold:
        speech_end = t0 + (c["t_end"] - clip)
        seg = next(
            (
                r
                for r in sent
                if r["shown"] in c["correct_refs"]
                and (r["conn"], r["seq"]) not in used
                and speech_end - 1.0 <= r["t_recv"] <= speech_end + wait
            ),
            None,
        )
        if seg is None:
            missed += 1
            continue
        used.add((seg["conn"], seg["seq"]))
        hops["server"].append(seg["t_sent"] - seg["t_recv"])
        if seg.get("t_client") is not None and seg.get("clock_offset") is not None:
            hops["stt"].append(seg["t_client"] + seg["clock_offset"] - speech_end)
        r = rendered.get((seg["conn"], seg["seq"]))
        if r is not None and r.get("clock_offset") is not None:
            t_screen = r["t_render"] + r["clock_offset"]
            hops["render"].append(t_screen - seg["t_sent"])
            hops["total"].append(t_screen - speech_end)
    return {
        "gold": len(gold),
        "matched": len(gold) - missed,
        "missed": missed,
        "hops": {k: _stats(v) for k, v in hops.items()},
    }


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("run", type=Path)
    p.add_argument("logs", type=Path, nargs="+", help="latency-YYYYMMDD.jsonl files")
    p.add_argument("--wait", type=float, default=WAIT_S)
    args = p.parse_args()
    run = json.loads(args.run.expanduser().read_text(encoding="utf-8"))
    d = corpus_dir() / run["sermon"]
    labels = [json.loads(line) for line in (d / "candidates.jsonl").open(encoding="utf-8")]
    labels = [c for c in labels if c.get("decision") in ("accept", "fix")]
    records = [
        json.loads(line)
        for path in args.logs
        for line in path.expanduser().read_text(encoding="utf-8").splitlines()
        if line
    ]
    result = measure(labels, run, records, args.wait)
    print(
        f"{run['sermon']} from {run['clip_start']:.0f} s: {result['matched']} of "
        f"{result['gold']} gold references reached the screen ({result['missed']} missed)"
    )
    for name, s in result["hops"].items():
        if s:
            print(
                f"  {name:7} n={s['n']:3}  p50 {s['p50_ms']} ms  "
                f"p95 {s['p95_ms']} ms  max {s['max_ms']} ms"
            )
        else:
            print(f"  {name:7} no data")
    out = run_path_out(args.run.expanduser())
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"wrote {out}")


def run_path_out(run_path: Path) -> Path:
    return run_path.with_name(run_path.stem + ".latency.json")


if __name__ == "__main__":
    main()
