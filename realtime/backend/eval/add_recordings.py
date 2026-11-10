#!/usr/bin/env python3
"""Add new sermon recordings to the evaluation corpus in one go.

For each recording, in order, skipping steps whose output already exists (so
a stopped run can simply be started again):

  1. a new folder sermon-NN in the corpus, with the recording and meta.json
     ("split": dev or test). A recording already in the corpus is not added twice.
  2. Whisper transcripts: whisper.json, and whisper.prompted.json (book names)
  3. review candidates: extract_candidates.py for dev, blind_candidates.py for
     test (times only, nothing about the content is shown)
  4. with --stream: the streaming decode cache for eval/full_eval.py (about as
     long as the recording; dev only unless --allow-test-stream)

It prints counts and file names only, never transcript text. Labels are then
made by a person with eval/review_labels.py (blind for test recordings).

The corpus is outside the repo, in $LIVEVERSE_CORPUS (default ~/liveverse-corpus).

Usage (from realtime/backend, with uv sync --group eval --group stt):
    uv run python eval/add_recordings.py --split dev ~/Downloads/20261116.mp3
    uv run python eval/add_recordings.py --split test a.mp3 b.mp3
    uv run python eval/add_recordings.py --split dev a.mp3 --stream
    uv run python eval/add_recordings.py --dry-run --split dev a.mp3
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".mp4", ".webm"}
FULL_S = 4200.0  # the stream cache length eval/full_eval.py expects


def corpus_dir() -> Path:
    return Path(os.environ.get("LIVEVERSE_CORPUS", "~/liveverse-corpus")).expanduser()


def existing_folder(src: Path) -> Path | None:
    """The corpus folder that already holds this recording (same name and size)."""
    for d in sorted(corpus_dir().glob("sermon-*")):
        other = d / src.name
        if other.exists() and other.stat().st_size == src.stat().st_size:
            return d
    return None


def next_folder() -> Path:
    numbers = [
        int(m.group(1))
        for d in corpus_dir().glob("sermon-*")
        if (m := re.fullmatch(r"sermon-(\d+)", d.name))
    ]
    return corpus_dir() / f"sermon-{max(numbers, default=0) + 1:02d}"


def run(step: str, cmd: list[str], dry: bool) -> None:
    print(f"  {step}: {' '.join(cmd[2:])}", flush=True)
    if dry:
        return
    # Tool output goes to a log next to the corpus, not the terminal: some tools
    # print statistics that are fine, but nothing here should show text.
    log = corpus_dir() / "reports" / "add-recordings.log"
    log.parent.mkdir(exist_ok=True)
    with log.open("a", encoding="utf-8") as f:
        f.write(f"\n## {datetime.now():%Y-%m-%d %H:%M} {step}: {' '.join(cmd)}\n")
        f.flush()
        done = subprocess.run(cmd, cwd=BACKEND, stdout=f, stderr=subprocess.STDOUT)
    if done.returncode != 0:
        raise SystemExit(f"  {step} failed (exit {done.returncode}); see {log}")


def add(src: Path, split: str, stream: bool, allow_test_stream: bool, dry: bool) -> str:
    src = src.expanduser().resolve()
    if src.suffix.lower() not in AUDIO_EXTS or not src.is_file():
        raise SystemExit(f"not an audio file: {src}")
    d = existing_folder(src)
    if d is not None:
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        if meta.get("split") != split:
            raise SystemExit(f"{src.name} is already {d.name} with split {meta.get('split')!r}")
        print(f"{src.name}: already {d.name}, continuing", flush=True)
    else:
        d = next_folder()
        print(f"{src.name}: new {d.name} ({split})", flush=True)
        if not dry:
            d.mkdir(parents=True)
            shutil.copy2(src, d / src.name)
            meta = {
                "sermon": d.name,
                "split": split,
                "source_file": src.name,
                "added": datetime.now().isoformat(timespec="seconds"),
                "runs": [],
            }
            (d / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    py = ["uv", "run", "python"]
    if not (d / "whisper.json").exists():
        run("transcribe", py + ["eval/transcribe.py", d.name], dry)
    if not (d / "whisper.prompted.json").exists():
        run("transcribe with prompt", py + ["eval/transcribe.py", d.name, "--prompt"], dry)
    if not (d / "candidates.jsonl").exists():
        tool = "eval/blind_candidates.py" if split == "test" else "eval/extract_candidates.py"
        run("candidates", py + [tool, d.name], dry)
    if stream:
        if split == "test" and not allow_test_stream:
            print("  stream cache: skipped for a test recording (--allow-test-stream)", flush=True)
        else:
            args = [
                "eval/stream_sim.py",
                "--config",
                "repeat1",
                "--windows",
                f"{d.name}:0",
                "--duration",
                str(FULL_S),
                "--pre",
                "0",
            ]
            if split == "test":
                args.append("--allow-test")
            run("stream cache", py + args, dry)
    return d.name


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("files", nargs="+", type=Path)
    p.add_argument(
        "--split",
        required=True,
        choices=["dev", "test"],
        help="dev: used for tuning; test: held out, reviewed blind",
    )
    p.add_argument("--stream", action="store_true", help="also build the streaming decode cache")
    p.add_argument(
        "--allow-test-stream",
        action="store_true",
        help="build the stream cache for test recordings too (after a freeze)",
    )
    p.add_argument("--dry-run", action="store_true", help="show the steps, change nothing")
    args = p.parse_args()
    names = [
        add(f, args.split, args.stream, args.allow_test_stream, args.dry_run) for f in args.files
    ]
    review = " ".join(names)
    print("\nNext: label the candidates (a person does this):")
    print(f"  uv run python eval/review_labels.py {review}")
    if args.split == "dev":
        print(
            f"Then score: uv run python eval/score.py {review} "
            "--transcript whisper.json --name <name>"
        )
    sys.exit(0)


if __name__ == "__main__":
    main()
