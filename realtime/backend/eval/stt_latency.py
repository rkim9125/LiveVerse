#!/usr/bin/env python3
"""Latency from the end of a spoken reference to the screen, for one replay.

For each gold reference in the played clip, the speech end is the end of the
mention in the Whisper transcript (word timestamps), put on the wall clock with
the run file:

    speech_end = t0 + (mention_end - clip_start)

The first segment in the latency log after that moment which changed the screen
to that reference gives the server times, and its rendered event gives the
screen time. Each hop is reported as p50 / p95 / max in milliseconds:

    stt        speech end to the client sending the segment that changed the
               screen (an interim one when interim display showed it first;
               missing when the hold timer showed it)
    server     server receive to state sent
    render     state sent to drawn on screen
    total      speech end to drawn on screen

References already on screen when said need no update and are counted apart.
References that never reached the screen within the wait are counted as missed.

Usage (from realtime/backend):
    uv run python eval/stt_latency.py ~/liveverse-corpus/sermon-01/runs/20261008-201500.json \\
        logs/latency-20261008.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
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


def gold_mentions(labels: list[dict], whisper_preds: list[tuple[float, float, str]]) -> list[dict]:
    """When each gold reference was said, in recording seconds.

    A label window is a whole Whisper segment (up to 30 s). The end of the
    mention itself comes from detect() on the Whisper transcript with word
    timestamps; labels where detect() did not find the reference fall back to
    the window end and are marked approximate."""
    out = []
    for c in labels:
        refs = c.get("correct_refs") or []
        if not refs:
            continue
        ends = [
            end
            for start, end, ref in whisper_preds
            if ref in refs and c["t_start"] - 1 <= start and end <= c["t_end"] + 1
        ]
        out.append({"refs": refs, "end": min(ends) if ends else c["t_end"], "approx": not ends})
    return sorted(out, key=lambda g: g["end"])


def key(r: dict) -> tuple:
    """A final and its interims share a sequence number."""
    return (r["conn"], r["seq"], bool(r.get("interim", False)))


def measure(gold: list[dict], run: dict, records: list[dict], wait: float = WAIT_S) -> dict:
    t0, clip = run["t0"], run["clip_start"]
    clip_end = clip + run.get("duration", float("inf"))
    gold = [g for g in gold if clip <= g["end"] <= clip_end]
    sent = sorted(
        (r for r in records if r.get("event") == "segment" and r.get("t_sent") and r.get("shown")),
        key=lambda r: r["t_sent"],
    )
    rendered = {
        (r["conn"], r["seq"], r.get("interim", False)): r
        for r in records
        if r.get("event") == "rendered" and r.get("t_render") is not None
    }
    hops: dict[str, list[float]] = {"stt": [], "server": [], "render": [], "total": []}
    missed = already = approx = from_interim = 0
    used: set[tuple[str, int]] = set()
    for g in gold:
        speech_end = t0 + (g["end"] - clip)
        before = [r for r in sent if t0 <= r["t_sent"] < speech_end - 1.0]
        if before and before[-1]["shown"] in g["refs"]:
            already += 1  # the screen already showed it: nothing to wait for
            continue
        seg = next(
            (
                r
                for r in sent
                if r["shown"] in g["refs"]
                and key(r) not in used
                and speech_end - 1.0 <= r["t_recv"] <= speech_end + wait
            ),
            None,
        )
        if seg is None:
            missed += 1
            continue
        approx += g["approx"]
        from_interim += bool(seg.get("interim"))
        used.add(key(seg))
        hops["server"].append(seg["t_sent"] - seg["t_recv"])
        if seg.get("t_client") is not None and seg.get("clock_offset") is not None:
            hops["stt"].append(seg["t_client"] + seg["clock_offset"] - speech_end)
        r = rendered.get(key(seg))
        if r is not None and r.get("clock_offset") is not None:
            t_screen = r["t_render"] + r["clock_offset"]
            hops["render"].append(t_screen - seg["t_sent"])
            hops["total"].append(t_screen - speech_end)
    screen = screen_accuracy(gold, run, sent, wait)
    return {
        "screen": screen,
        "gold": len(gold),
        "already_shown": already,
        "matched": len(gold) - missed - already,
        "missed": missed,
        "approx_times": approx,
        "from_interim": from_interim,
        "hops": {k: _stats(v) for k, v in hops.items()},
    }


def screen_accuracy(gold: list[dict], run: dict, sent: list[dict], wait: float = WAIT_S) -> dict:
    """What the screen did during the run, interim updates included.

    changes   times the screen moved to another passage
    correct   changes to a gold reference said within the wait before (or 1 s after)
    reverts   interim displays taken back because the final did not contain them
    """
    t0, clip = run["t0"], run["clip_start"]
    t_end = t0 + run.get("duration", float("inf")) + wait
    changes = correct = reverts = 0
    last = None
    for r in sent:
        if not t0 <= r["t_sent"] <= t_end:
            continue
        if r.get("reason") == "revert":
            reverts += 1
        if r["shown"] == last:
            continue
        last = r["shown"]
        changes += 1
        said = clip + (r["t_sent"] - t0)
        correct += any(
            r["shown"] in g["refs"] and said - wait <= g["end"] <= said + 1 for g in gold
        )
    return {
        "changes": changes,
        "correct": correct,
        "precision": round(correct / changes, 3) if changes else 0.0,
        "reverts": reverts,
    }


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("run", type=Path)
    p.add_argument("logs", type=Path, nargs="+", help="latency-YYYYMMDD.jsonl files")
    p.add_argument("--wait", type=float, default=WAIT_S)
    p.add_argument("--whisper", default="whisper.json", help="transcript with word times")
    args = p.parse_args()
    run = json.loads(args.run.expanduser().read_text(encoding="utf-8"))
    d = corpus_dir() / run["sermon"]
    labels = [json.loads(line) for line in (d / "candidates.jsonl").open(encoding="utf-8")]
    labels = [c for c in labels if c.get("decision") in ("accept", "fix")]
    gold = gold_mentions(labels, whisper_predictions(d / args.whisper))
    records = [
        json.loads(line)
        for path in args.logs
        for line in path.expanduser().read_text(encoding="utf-8").splitlines()
        if line
    ]
    result = measure(gold, run, records, args.wait)
    print(
        f"{run['sermon']} from {run['clip_start']:.0f} s: {result['matched']} of "
        f"{result['gold']} gold references reached the screen ({result['already_shown']} "
        f"already shown, {result['missed']} missed, {result['approx_times']} approximate times, "
        f"{result['from_interim']} from interim results)"
    )
    sc = result["screen"]
    print(
        f"  screen: {sc['changes']} changes, {sc['correct']} correct "
        f"(precision {sc['precision']}), {sc['reverts']} interim reverts"
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


def whisper_predictions(path: Path) -> list[tuple[float, float, str]]:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from score import predictions

    return predictions(path)


def run_path_out(run_path: Path) -> Path:
    return run_path.with_name(run_path.stem + ".latency.json")


if __name__ == "__main__":
    main()
