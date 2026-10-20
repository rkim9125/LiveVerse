#!/usr/bin/env python3
"""Whisper streaming, simulated offline with a virtual clock.

Running the worker at live pace takes 10 minutes per window. This runs the
same pieces (Silero VAD, the segmenter, mlx-whisper with the book prompt, the
session with its interim display policy) as fast as the decoder allows, and
keeps a virtual clock: a decode starts when the audio it needs has arrived and
the decoder is free, and its result arrives after the time the decode really
took. The session gets each result at that virtual time, so screen latency is
what a live run on this computer would see (minus the WebSocket and render,
about 20 ms).

Reported per configuration and window:
  shown30 / in3 / in2 / in1.5   gold references shown within that many seconds
  p50 / p95                     speech end (Whisper word times) to screen
  screen                        screen changes and how many were right
  F1                            the finals scored with score.py (slack 1 s)

Usage (from realtime/backend, dev sermons only):
    uv run python eval/stream_sim.py --config base max8 interim05 \\
        --windows sermon-01:180 sermon-02:3300
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from collections import deque
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import Settings  # noqa: E402
from app.core.session import Session  # noqa: E402
from app.core.store import BibleStore  # noqa: E402
from app.main import _quote_index  # noqa: E402
from stt_worker.decoder import MlxDecoder  # noqa: E402
from stt_worker.prompt import book_prompt  # noqa: E402
from stt_worker.segmenter import SR, Segmenter, SegmenterConfig  # noqa: E402

FRAME = 512
WAIT_S = 30.0


@dataclass(frozen=True)
class SimConfig:
    name: str
    segmenter: SegmenterConfig = SegmenterConfig()
    interim_s: float = 1.0
    interim_min_s: float = 0.5
    tail_s: float | None = None  # interims decode only the last tail_s seconds
    repeats: int = 2  # session: consecutive interims to show a verse
    hold_s: float = 0.7  # session: or this long in the interim results


CONFIGS = {
    c.name: c
    for c in [
        SimConfig("base"),
        SimConfig("max8", SegmenterConfig(max_s=8.0)),
        SimConfig("max6", SegmenterConfig(max_s=6.0)),
        SimConfig("interim05", interim_s=0.5),
        SimConfig("repeat1", repeats=1),
        SimConfig("tail6", tail_s=6.0),
        SimConfig("soft", SegmenterConfig(short_after_s=5.0, short_hangover_s=0.2)),
        SimConfig("soft+max8", SegmenterConfig(max_s=8.0, short_after_s=5.0, short_hangover_s=0.2)),
        SimConfig(
            "soft+max8+repeat1",
            SegmenterConfig(max_s=8.0, short_after_s=5.0, short_hangover_s=0.2),
            repeats=1,
        ),
        SimConfig("max8+repeat1", SegmenterConfig(max_s=8.0), repeats=1),
    ]
}


def corpus_dir() -> Path:
    return Path(os.environ.get("LIVEVERSE_CORPUS", "~/liveverse-corpus")).expanduser()


def vad_probs(audio: np.ndarray) -> list[float]:
    from stt_worker.vad import SileroVAD

    vad = SileroVAD()
    vad.reset()
    return [vad(audio[i * FRAME : (i + 1) * FRAME]) for i in range(len(audio) // FRAME)]


def simulate(audio: np.ndarray, probs: list[float], cfg: SimConfig, decoder) -> list[dict]:
    """Events {t, seq, final, text, start, end} in virtual seconds from the clip start."""
    seg = Segmenter(cfg.segmenter)
    finals: deque = deque()  # (seq, utterance, available at)
    interim = None  # (seq, utterance, available at), latest only
    seq, last_interim_end, busy = 1, 0.0, 0.0
    events: list[dict] = []

    def run_jobs(now: float, drain: bool = False) -> None:
        nonlocal interim, busy
        while True:
            if finals:
                s, u, avail = finals[0]
                start = max(busy, avail)
                if start > now and not drain:
                    return
                finals.popleft()
                d = decoder.decode(u.audio)
                busy = start + d.seconds
                events.append(
                    {
                        "t": busy,
                        "seq": s,
                        "final": True,
                        "text": d.text,
                        "start": u.start,
                        "end": u.end,
                    }
                )
            elif interim is not None:
                s, u, avail = interim
                start = max(busy, avail)
                if start > now and not drain:
                    return
                interim = None
                if s != seq:
                    continue  # finished meanwhile; its final is queued
                audio_ = u.audio
                if cfg.tail_s is not None:
                    audio_ = audio_[-int(cfg.tail_s * SR) :]
                d = decoder.decode(audio_)
                busy = start + d.seconds
                events.append(
                    {
                        "t": busy,
                        "seq": s,
                        "final": False,
                        "text": d.text,
                        "start": u.start,
                        "end": u.end,
                    }
                )
            else:
                return

    for i, p in enumerate(probs):
        now = (i + 1) * FRAME / SR
        for u in seg.push(audio[i * FRAME : (i + 1) * FRAME], p):
            finals.append((seq, u, now))
            if interim is not None and interim[0] == seq:
                interim = None
            seq += 1
            last_interim_end = u.end
        if seg.active:
            cur = seg.current()
            if (
                cur.end - cur.start >= cfg.interim_min_s
                and cur.end - max(last_interim_end, cur.start) >= cfg.interim_s
            ):
                interim = (seq, cur, now)
                last_interim_end = cur.end
        run_jobs(now)
    for u in seg.flush():
        finals.append((seq, u, len(probs) * FRAME / SR))
        seq += 1
    run_jobs(float("inf"), drain=True)
    return sorted(events, key=lambda e: e["t"])


def replay(events: list[dict], session: Session) -> list[dict]:
    """Feed events to the session at their times. Returns the screen history."""
    for e in events:
        due = session.interim_due()
        if due is not None and due <= e["t"]:
            session.tick(due)
        if e["final"]:
            session.process_final(e["text"], now=e["t"], seq=e["seq"])
        else:
            session.process_interim(e["text"], now=e["t"], seq=e["seq"])
    due = session.interim_due()
    if due is not None:
        session.tick(due)
    return session.history


def measure(history: list[dict], gold: list[dict], clip: float, duration: float) -> dict:
    gold = [g for g in gold if clip <= g["end"] <= clip + duration]
    lat, already, missed = [], 0, 0
    for g in gold:
        end = g["end"] - clip
        before = [h for h in history if h["t"] < end - 1.0]
        if before and before[-1]["ref"] in g["refs"]:
            already += 1
            continue
        hit = next(
            (h for h in history if h["ref"] in g["refs"] and end - 1.0 <= h["t"] <= end + WAIT_S),
            None,
        )
        if hit is None:
            missed += 1
        else:
            lat.append(max(0.0, hit["t"] - end))
    changes = correct = reverts = 0
    last = None
    for h in history:
        reverts += h["reason"] == "revert"
        if h["ref"] == last or h["ref"] is None:
            last = h["ref"]
            continue
        last = h["ref"]
        changes += 1
        correct += any(
            h["ref"] in g["refs"] and h["t"] - WAIT_S <= g["end"] - clip <= h["t"] + 1 for g in gold
        )
    n = len(gold) - already
    s = sorted(lat)

    def q(x: float) -> float | None:
        return round(s[min(len(s) - 1, round(x * (len(s) - 1)))], 2) if s else None

    return {
        "gold": n,
        "shown30": len(s),
        "in3": sum(v <= 3 for v in s),
        "in2": sum(v <= 2 for v in s),
        "in1_5": sum(v <= 1.5 for v in s),
        "p50": round(statistics.median(s), 2) if s else None,
        "p95": q(0.95),
        "max": round(s[-1], 2) if s else None,
        "slow": [round(v, 1) for v in s if v > 3],
        "changes": changes,
        "correct": correct,
        "reverts": reverts,
    }


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--config", nargs="+", default=["base"], choices=sorted(CONFIGS))
    p.add_argument("--windows", nargs="+", default=["sermon-01:180", "sermon-02:3300"])
    p.add_argument("--duration", type=float, default=600.0)
    args = p.parse_args()

    import score
    from mlx_whisper.audio import load_audio
    from stt_latency import gold_mentions, whisper_predictions

    settings = Settings.from_env()
    store = BibleStore.load(settings.bible_text_path)
    quotes = _quote_index(store) if settings.quote_search else None
    score.QUOTES["index"] = quotes  # score the finals as score.py --quotes would
    decoder = MlxDecoder("turbo", prompt=book_prompt())
    decoder.warm_up()
    results = []
    for w in args.windows:
        sermon, clip = w.split(":")
        clip = float(clip)
        d = corpus_dir() / sermon
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        if meta.get("split") != "dev":
            raise SystemExit(f"{sermon} is not a dev sermon")
        audio = np.array(load_audio(str(d / "audio.wav")), dtype=np.float32)
        audio = audio[int(clip * SR) : int((clip + args.duration) * SR)]
        probs = vad_probs(audio)
        labels = [json.loads(line) for line in (d / "candidates.jsonl").open(encoding="utf-8")]
        labels = [c for c in labels if c.get("decision") in ("accept", "fix")]
        gold = gold_mentions(labels, whisper_predictions(d / "whisper.json"))
        for name in args.config:
            cfg = CONFIGS[name]
            t = time.time()
            events = simulate(audio, probs, cfg, decoder)
            s = replace(settings, interim_repeats=cfg.repeats, interim_hold_s=cfg.hold_s)
            history = replay(events, Session(store, s, quotes=quotes))
            m = measure(history, gold, clip, args.duration)
            out = f"whisperstream.sim-{name}.json"
            segs = [
                {
                    "start": round(clip + e["start"], 2),
                    "end": round(clip + e["end"], 2),
                    "text": e["text"],
                }
                for e in events
                if e["final"]
            ]
            (d / out).write_text(
                json.dumps(
                    {"source": "stream_sim", "config": name, "segments": segs}, ensure_ascii=False
                )
            )
            sc = score.score_sermon(sermon, out, clip, clip + args.duration, 1.0)
            strict = score.metrics(sc["tp"], sc["fp"], sc["fn"])
            m |= {
                "f1": strict["f1"],
                "tp": sc["tp"],
                "fp": sc["fp"],
                "fn": sc["fn"],
                "finals": len(segs),
                "interims": sum(not e["final"] for e in events),
                "sim_s": round(time.time() - t),
            }
            results.append({"window": w, "config": name, **m})
            print(json.dumps(results[-1]), flush=True)
    out = corpus_dir() / "reports" / f"stream-sim-{time.strftime('%Y%m%d-%H%M')}.json"
    out.write_text(json.dumps(results, indent=1))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
