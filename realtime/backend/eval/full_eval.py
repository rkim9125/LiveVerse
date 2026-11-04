#!/usr/bin/env python3
"""Compare detector variants on whole dev sermons, from cached streaming decodes.

eval/stream_sim.py decodes a sermon once with the Whisper streaming settings
and caches the interim and final results with their virtual times. This
replays them through the session and the scorer with each variant's switches,
so detector changes can be compared in seconds instead of hours:

  F1            the finals scored by score.py (strict, quotes on)
  shown30/in3   gold references on screen within 30 s / 3 s of being said
  p50/p95       speech end to screen, for those shown
  wrong         screen changes to a passage that was not just said
  reverts       interim displays taken back

Each sermon is reported on its own, so a change that helps only one shows.

Usage (from realtime/backend, after the caches exist):
    uv run python eval/stream_sim.py --config repeat1 --windows sermon-01:0 --duration 4200 --pre 0
    uv run python eval/full_eval.py --variants base joins
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import score  # noqa: E402
import stream_sim as sim  # noqa: E402
from stt_latency import gold_mentions, whisper_predictions  # noqa: E402

from app.config import Settings  # noqa: E402
from app.core.session import Session  # noqa: E402
from app.core.store import BibleStore  # noqa: E402
from app.main import _quote_index  # noqa: E402

FULL_S = 4200.0  # longer than either dev sermon

# Each variant: settings overrides (the session) and score.CARRY overrides (the scorer).
VARIANTS: dict[str, dict] = {
    "base": {
        "settings": {"join_chapter": False, "join_runs": False},
        "carry": {"join_chapter": False, "join_runs": False},
    },
    "h": {
        "settings": {"join_chapter": True, "join_runs": False},
        "carry": {"join_chapter": True, "join_runs": False},
    },
    "d": {
        "settings": {"join_chapter": False, "join_runs": True},
        "carry": {"join_chapter": False, "join_runs": True},
    },
    "joins": {"settings": {}, "carry": {}},  # current defaults
}


def evaluate(sermon: str, variant: dict, store, quotes, settings) -> dict:
    d = sim.corpus_dir() / sermon
    cache = sim.events_cache(sermon, 0.0, FULL_S, 0.0, sim.CONFIGS["repeat1"])
    if not cache.exists():
        raise SystemExit(f"no cached decode for {sermon}: {cache.name}; run stream_sim first")
    events = json.loads(cache.read_text())
    s = replace(settings, interim_repeats=1, **variant.get("settings", {}))
    history = sim.replay(events, Session(store, s, quotes=quotes))
    labels = [json.loads(line) for line in (d / "candidates.jsonl").open(encoding="utf-8")]
    labels = [c for c in labels if c.get("decision") in ("accept", "fix")]
    gold = gold_mentions(labels, whisper_predictions(d / "whisper.json"))
    m = sim.measure(history, gold, 0.0, FULL_S, 0.0)
    name = "whisperstream.full-sim.json"
    segs = [{"start": e["start"], "end": e["end"], "text": e["text"]} for e in events if e["final"]]
    (d / name).write_text(json.dumps({"source": "full_eval", "segments": segs}, ensure_ascii=False))
    saved = dict(score.CARRY)
    score.CARRY.update(variant.get("carry", {}))
    try:
        sc = score.score_sermon(sermon, name)
    finally:
        score.CARRY.clear()
        score.CARRY.update(saved)
    strict = score.metrics(sc["tp"], sc["fp"], sc["fn"])
    return {
        "f1": strict["f1"],
        "tp": sc["tp"],
        "fp": sc["fp"],
        "fn": sc["fn"],
        "gold": m["gold"],
        "shown30": m["shown30"],
        "in3": m["in3"],
        "p50": m["p50"],
        "p95": m["p95"],
        "changes": m["changes"],
        "wrong": m["changes"] - m["correct"],
        "reverts": m["reverts"],
    }


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--variants", nargs="+", default=list(VARIANTS), choices=sorted(VARIANTS))
    p.add_argument("--sermons", nargs="+", default=["sermon-01", "sermon-02"])
    args = p.parse_args()
    settings = Settings.from_env()
    store = BibleStore.load(settings.bible_text_path)
    quotes = _quote_index(store) if settings.quote_search else None
    score.QUOTES["index"] = quotes
    rows = []
    for v in args.variants:
        for sermon in args.sermons:
            r = {
                "variant": v,
                "sermon": sermon,
                **evaluate(sermon, VARIANTS[v], store, quotes, settings),
            }
            rows.append(r)
            print(
                f"{v:12} {sermon}  F1 {r['f1']:.3f} (tp {r['tp']} fp {r['fp']} fn {r['fn']})  "
                f"shown30 {r['shown30']}/{r['gold']} in3 {r['in3']}  "
                f"p50 {r['p50']} p95 {r['p95']}  "
                f"wrong {r['wrong']}/{r['changes']} reverts {r['reverts']}",
                flush=True,
            )
    out = sim.corpus_dir() / "reports" / "full-eval-latest.json"
    out.write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
