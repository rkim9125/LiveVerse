#!/usr/bin/env python3
"""Transcribe a sermon recording with local Whisper (mlx-whisper, Apple Silicon).

The corpus lives outside the repo, in $LIVEVERSE_CORPUS (default ~/liveverse-corpus):

    ~/liveverse-corpus/sermon-01/<original>.mp3
    ~/liveverse-corpus/sermon-01/audio.wav          16 kHz mono, written by this script
    ~/liveverse-corpus/sermon-01/whisper.json        segments with word timestamps
    ~/liveverse-corpus/sermon-01/transcript.txt      "[mm:ss] text" per segment
    ~/liveverse-corpus/sermon-01/meta.json           source, timing of each run

Usage (from realtime/backend):
    uv sync --group eval
    uv run python eval/transcribe.py sermon-01                         # whole recording
    uv run python eval/transcribe.py sermon-01 --start 1800 --duration 300 --name sample
    uv run python eval/transcribe.py sermon-01 --prompt                # bias toward book names
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.detect.books import BOOKS  # noqa: E402

DEFAULT_MODEL = "mlx-community/whisper-large-v3-turbo"
AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".mp4", ".webm"}

# Whisper keeps at most n_text_ctx // 2 - 1 = 223 prompt tokens and drops the front
# of anything longer. All 66 names take 267 tokens, so these rarely preached short
# books are left out to make the rest fit (217 tokens).
PROMPT_MAX_TOKENS = 223
PROMPT_LEFT_OUT = [
    "오바댜",
    "나훔",
    "하박국",
    "스바냐",
    "학개",
    "요엘",
    "빌레몬서",
    "유다서",
    "요한이서",
    "요한삼서",
    "아가",
    "스가랴",
    "예레미야애가",
]


def corpus_dir() -> Path:
    return Path(os.environ.get("LIVEVERSE_CORPUS", "~/liveverse-corpus")).expanduser()


def find_source(sermon_dir: Path) -> Path:
    sources = [
        p
        for p in sermon_dir.iterdir()
        if p.suffix.lower() in AUDIO_EXTS and not p.name.startswith(("audio", "sample"))
    ]
    if len(sources) != 1:
        raise SystemExit(f"expected one source recording in {sermon_dir}, found {len(sources)}")
    return sources[0]


def to_wav(src: Path, dst: Path, start: float | None, duration: float | None) -> None:
    cmd = ["ffmpeg", "-v", "error", "-y"]
    if start is not None:
        cmd += ["-ss", str(start)]
    if duration is not None:
        cmd += ["-t", str(duration)]
    cmd += ["-i", str(src), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dst)]
    subprocess.run(cmd, check=True)


def wav_seconds(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(out.stdout.strip())


def book_prompt() -> str:
    return " ".join(b.ko for b in BOOKS if b.ko not in PROMPT_LEFT_OUT)


def prompt_tokens(prompt: str) -> int:
    from mlx_whisper.tokenizer import get_tokenizer

    tokenizer = get_tokenizer(True, num_languages=100, language="ko", task="transcribe")
    return len(tokenizer.encode(" " + prompt.strip()))


def carry_prompt_to_every_window(prompt: str) -> None:
    """Use the prompt for every 30 s window, not only the first.

    mlx-whisper 0.4.3 resets the prompt after the first window when
    condition_on_previous_text is False, and has no carry_initial_prompt option.
    The transcribe module builds DecodingOptions for each window, so wrap it and
    fill in the prompt whenever the window has none.
    """
    module = importlib.import_module("mlx_whisper.transcribe")
    original = module.DecodingOptions

    def options(*args, **kwargs):
        if not kwargs.get("prompt"):
            kwargs["prompt"] = prompt
        return original(*args, **kwargs)

    module.DecodingOptions = options


def fmt_time(t: float) -> str:
    m, s = divmod(int(t), 60)
    return f"{m:02d}:{s:02d}"


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("sermon", help="folder name under the corpus, e.g. sermon-01")
    p.add_argument("--start", type=float, help="clip start in seconds")
    p.add_argument("--duration", type=float, help="clip length in seconds")
    p.add_argument("--name", default="", help="output prefix, e.g. 'sample' -> sample.whisper.json")
    p.add_argument(
        "--prompt", action="store_true", help="prompt every window with Bible book names"
    )
    p.add_argument("--model", default=DEFAULT_MODEL)
    args = p.parse_args()

    import mlx_whisper  # only needed here; installed with --group eval

    sermon_dir = corpus_dir() / args.sermon
    src = find_source(sermon_dir)
    prefix = f"{args.name}." if args.name else ""
    wav = sermon_dir / f"{args.name or 'audio'}.wav"
    variant = "whisper.prompted" if args.prompt else "whisper"

    t0 = time.perf_counter()
    to_wav(src, wav, args.start, args.duration)
    convert_s = time.perf_counter() - t0
    audio_s = wav_seconds(wav)

    prompt = book_prompt() if args.prompt else None
    n_prompt_tokens = prompt_tokens(prompt) if prompt else 0
    if n_prompt_tokens > PROMPT_MAX_TOKENS:
        raise SystemExit(f"prompt is {n_prompt_tokens} tokens, limit {PROMPT_MAX_TOKENS}")
    if prompt:
        carry_prompt_to_every_window(prompt)

    t0 = time.perf_counter()
    result = mlx_whisper.transcribe(
        str(wav),
        path_or_hf_repo=args.model,
        language="ko",
        word_timestamps=True,
        condition_on_previous_text=False,  # avoids repetition loops on long recordings
    )
    transcribe_s = time.perf_counter() - t0

    offset = args.start or 0.0
    for seg in result["segments"]:  # store times relative to the full recording
        seg["start"] += offset
        seg["end"] += offset
        for w in seg.get("words", []):
            w["start"] += offset
            w["end"] += offset

    (sermon_dir / f"{prefix}{variant}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    lines = [f"[{fmt_time(s['start'])}] {s['text'].strip()}" for s in result["segments"]]
    (sermon_dir / f"{prefix}{variant}.transcript.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )

    meta_path = sermon_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    meta.setdefault("sermon", args.sermon)
    meta["source_file"] = src.name
    run = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "output": f"{prefix}{variant}.json",
        "model": args.model,
        "prompt": args.prompt,
        "prompt_mode": "every-window" if args.prompt else None,
        "prompt_tokens": n_prompt_tokens,
        "clip_start": args.start,
        "audio_seconds": round(audio_s, 1),
        "convert_seconds": round(convert_s, 1),
        "transcribe_seconds": round(transcribe_s, 1),
        "realtime_factor": round(audio_s / transcribe_s, 1),
        "segments": len(result["segments"]),
    }
    meta.setdefault("runs", []).append(run)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(run, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
