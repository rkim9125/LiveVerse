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

# Each variant: which improvements are on. The base has none of the ones made
# in this round; "+x" adds one alone; "all" is the current defaults.
OFF = {"join_chapter": False, "join_runs": False, "join_tens": False, "verse_as_je": False}


def _variant(**on) -> dict:
    flags = OFF | on
    carry = {k: flags[k] for k in ("join_chapter", "join_runs", "join_tens")}
    reading = {k: flags.get(k, False) for k in ("reading", "reading_fill")}
    return {"settings": carry | reading, "carry": carry, "verse_as_je": flags["verse_as_je"]}


ALL = {"join_chapter": True, "join_runs": True, "join_tens": True, "verse_as_je": True}
VARIANTS: dict[str, dict] = {
    "base": _variant(),
    "+h": _variant(join_chapter=True),
    "+d": _variant(join_runs=True),
    "+a": _variant(verse_as_je=True),
    "+b": _variant(join_tens=True),
    "+f": _variant(reading=True),
    "+f+fill": _variant(reading=True, reading_fill=True),
    "all": _variant(**ALL),
    "all+f": _variant(**ALL, reading=True),
    "all+f+fill": _variant(**ALL, reading=True, reading_fill=True),
    "+g": _variant() | {"revisions": True},
    "all+g": _variant(**ALL) | {"revisions": True},
    "all+f+g": _variant(**ALL, reading=True) | {"revisions": True},
}


def with_revisions(sermon: str, events: list[dict]) -> tuple[list[dict], dict[int, str]]:
    """Events with the revisions of revise_sim.py added at their arrival time,
    and the revised text of each final whose revision arrived before the next
    final (the ones the session takes)."""
    from revise_sim import revisions_path

    path = revisions_path(sermon)
    if not path.exists():
        raise SystemExit(f"no revisions for {sermon}; run eval/revise_sim.py first")
    revs = json.loads(path.read_text())
    finals = [e for e in events if e["final"]]
    next_t = {e["seq"]: n["t"] for e, n in zip(finals, finals[1:], strict=False)}
    added, applied = [], {}
    for e in finals:
        r = revs.get(str(e["seq"]))
        if not r or not r["text"] or r["text"] == e["text"]:
            continue
        t = e["t"] + r["seconds"]
        added.append(e | {"t": t, "text": r["text"], "revision": True})
        if t < next_t.get(e["seq"], float("inf")):
            applied[e["seq"]] = r["text"]
    return sorted(events + added, key=lambda e: e["t"]), applied


def evaluate(sermon: str, variant: dict, store, quotes, settings) -> dict:
    from app.detect import normalize

    normalize.VERSE_AS_JE = variant["verse_as_je"]
    d = sim.corpus_dir() / sermon
    cache = sim.events_cache(sermon, 0.0, FULL_S, 0.0, sim.CONFIGS["repeat1"])
    if not cache.exists():
        raise SystemExit(f"no cached decode for {sermon}: {cache.name}; run stream_sim first")
    events = json.loads(cache.read_text())
    applied: dict[int, str] = {}
    if variant.get("revisions"):
        events, applied = with_revisions(sermon, events)
    s = replace(settings, interim_repeats=1, **variant.get("settings", {}))
    history = sim.replay(events, Session(store, s, quotes=quotes))
    labels = [json.loads(line) for line in (d / "candidates.jsonl").open(encoding="utf-8")]
    labels = [c for c in labels if c.get("decision") in ("accept", "fix")]
    gold = gold_mentions(labels, whisper_predictions(d / "whisper.json"))
    m = sim.measure(history, gold, 0.0, FULL_S, 0.0)
    name = "whisperstream.full-sim.json"
    segs = [
        {"start": e["start"], "end": e["end"], "text": applied.get(e["seq"], e["text"])}
        for e in events
        if e["final"] and not e.get("revision")
    ]
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
