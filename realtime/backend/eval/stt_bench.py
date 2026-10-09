#!/usr/bin/env python3
"""How long one mlx-whisper call takes on short pieces of a sermon.

Streaming decodes short pieces (one utterance cut by VAD, up to about 12 s)
instead of 30 s windows. This times single calls by piece length, model, with
and without the book name prompt, and with word timestamps (needed for the
final of each utterance). No transcript text is printed or saved.

Usage (from realtime/backend, dev sermons only):
    uv run --group eval python eval/stt_bench.py sermon-01
    uv run --group eval python eval/stt_bench.py sermon-01 --models turbo small medium --reps 5
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stt_worker.prompt import book_prompt  # noqa: E402

MODELS = {
    "turbo": "mlx-community/whisper-large-v3-turbo",
    "medium": "mlx-community/whisper-medium-mlx",
    "small": "mlx-community/whisper-small-mlx",
}
SR = 16000


def corpus_dir() -> Path:
    return Path(os.environ.get("LIVEVERSE_CORPUS", "~/liveverse-corpus")).expanduser()


def decode(audio, repo: str, prompt: str | None, words: bool) -> float:
    import mlx_whisper

    t = time.perf_counter()
    mlx_whisper.transcribe(
        audio,
        path_or_hf_repo=repo,
        language="ko",
        initial_prompt=prompt,
        word_timestamps=words,
        temperature=0.0,
        condition_on_previous_text=False,
        verbose=None,
    )
    return time.perf_counter() - t


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("sermon")
    p.add_argument("--models", nargs="+", default=["turbo", "small", "medium"])
    p.add_argument("--lengths", nargs="+", type=float, default=[1, 2, 4, 8, 12])
    p.add_argument("--reps", type=int, default=5, help="pieces per length (different places)")
    args = p.parse_args()

    from mlx_whisper.audio import load_audio

    d = corpus_dir() / args.sermon
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    if meta.get("split") != "dev":
        raise SystemExit(f"{args.sermon} is not a dev sermon")
    audio = load_audio(str(d / "audio.wav"))
    total = len(audio) / SR
    starts = [total * (i + 1) / (args.reps + 1) for i in range(args.reps)]
    prompt = book_prompt()
    rows = []
    for name in args.models:
        repo = MODELS[name]
        decode(audio[: SR * 2], repo, prompt, False)  # load and warm up
        for length in args.lengths:
            for mode, use_prompt, words in (
                ("plain", False, False),
                ("prompt", True, False),
                ("prompt+words", True, True),
            ):
                times = [
                    decode(
                        audio[int(s * SR) : int((s + length) * SR)],
                        repo,
                        prompt if use_prompt else None,
                        words,
                    )
                    for s in starts
                ]
                row = {
                    "model": name,
                    "length_s": length,
                    "mode": mode,
                    "p50_ms": round(statistics.median(times) * 1000),
                    "max_ms": round(max(times) * 1000),
                }
                rows.append(row)
                print(
                    f"{name:6} {length:4.0f} s  {mode:13} p50 {row['p50_ms']:5} ms  "
                    f"max {row['max_ms']:5} ms",
                    flush=True,
                )
    out = corpus_dir() / "reports" / f"stt-bench-{datetime.now():%Y%m%d-%H%M}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"sermon": args.sermon, "reps": args.reps, "rows": rows}, indent=1))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
