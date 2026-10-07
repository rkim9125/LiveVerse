#!/usr/bin/env python3
"""Play part of a recorded sermon into an audio device (for example BlackHole),
so the browser's speech recognition hears it as microphone input.

The browser then sends the audio to its speech service (Google, for Chrome's
Web Speech API). Do this only with the preacher's permission for that use;
the script refuses to play without --consent-confirmed.

It records a run file with the wall-clock start (t0) so the browser capture
can be put on the recording's timeline afterwards (capture_to_segments.py).

Usage (from realtime/backend):
    uv run python eval/play_to_device.py --list-devices
    uv run python eval/play_to_device.py sermon-01 --auto --dry-run
    uv run python eval/play_to_device.py sermon-01 --auto --device "BlackHole 2ch" \\
        --consent-confirmed
    uv run python eval/play_to_device.py sermon-01 --start 1320 --duration 600 \\
        --device "Multi-Output Device" --consent-confirmed
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".mp4", ".webm"}
DEVICE_RE = re.compile(r"\[(\d+)\]\s+(.+?),\s*(\S+)\s*$")


def corpus_dir() -> Path:
    return Path(os.environ.get("LIVEVERSE_CORPUS", "~/liveverse-corpus")).expanduser()


def list_devices() -> list[tuple[int, str]]:
    out = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=16000:cl=mono",
            "-t",
            "0.01",
            "-f",
            "audiotoolbox",
            "-list_devices",
            "true",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    return parse_devices(out.stderr)


def parse_devices(text: str) -> list[tuple[int, str]]:
    found = []
    for line in text.splitlines():
        m = DEVICE_RE.search(line.split("]", 1)[-1] if line.startswith("[AudioToolbox") else line)
        if m and m.group(2) != "(null)":
            found.append((int(m.group(1)), m.group(2).strip()))
    return found


def densest_window(
    labels: list[dict], length: float = 600.0, step: float = 60.0
) -> tuple[float, int]:
    """Start time of the window with the most gold references, and that count."""
    times = [c["t_start"] for c in labels if c.get("correct_refs")]
    if not times:
        return 0.0, 0
    best = (0.0, -1)
    start = 0.0
    while start <= max(times):
        n = sum(1 for t in times if start <= t < start + length)
        if n > best[1]:
            best = (start, n)
        start += step
    return best


def source_file(sermon_dir: Path) -> Path:
    files = [
        p
        for p in sermon_dir.iterdir()
        if p.suffix.lower() in AUDIO_EXTS and not p.name.startswith(("audio", "sample"))
    ]
    if len(files) != 1:
        raise SystemExit(f"expected one recording in {sermon_dir}, found {len(files)}")
    return files[0]


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("sermon", nargs="?")
    p.add_argument("--list-devices", action="store_true")
    p.add_argument("--device", default="BlackHole 2ch")
    p.add_argument("--start", type=float)
    p.add_argument("--duration", type=float, default=600.0)
    p.add_argument("--auto", action="store_true", help="pick the 10 minutes with the most labels")
    p.add_argument("--dry-run", action="store_true", help="show what would play, play nothing")
    p.add_argument(
        "--consent-confirmed",
        action="store_true",
        help="the preacher allowed sending this recording to the speech service",
    )
    args = p.parse_args()

    if args.list_devices:
        for idx, name in list_devices():
            print(f"[{idx}] {name}")
        return
    if not args.sermon:
        p.error("give a sermon folder name, e.g. sermon-01")

    d = corpus_dir() / args.sermon
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    if meta.get("split") != "dev":
        raise SystemExit(f"{args.sermon} is not a dev sermon; test sermons are not used here")
    if args.auto:
        labels = [json.loads(line) for line in (d / "candidates.jsonl").open(encoding="utf-8")]
        start, n = densest_window(labels, args.duration)
        print(f"densest {args.duration:.0f} s window starts at {start:.0f} s ({n} gold references)")
    elif args.start is None:
        p.error("give --start or --auto")
    else:
        start = args.start

    src = source_file(d)
    if args.dry_run:
        print(
            "would play:", src.name, f"from {start:.0f} s for {args.duration:.0f} s to", args.device
        )
        return
    if not args.consent_confirmed:
        raise SystemExit("refusing to play: add --consent-confirmed once the preacher has agreed")
    devices = dict((name, idx) for idx, name in list_devices())
    if args.device not in devices:
        raise SystemExit(f"device {args.device!r} not found; try --list-devices")
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-re",
        "-ss",
        str(start),
        "-t",
        str(args.duration),
        "-i",
        str(src),
        "-f",
        "audiotoolbox",
        "-audio_device_index",
        str(devices[args.device]),
        "-",
    ]

    runs = d / "runs"
    runs.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_path = runs / f"{stamp}.json"
    t0 = time.time()
    run = {
        "sermon": args.sermon,
        "clip_start": start,
        "duration": args.duration,
        "device": args.device,
        "t0": t0,
        "created": stamp,
    }
    run_path.write_text(json.dumps(run, indent=2), encoding="utf-8")
    print(f"playing; run file {run_path}")
    code = subprocess.run(cmd).returncode
    run["t_end"] = time.time()
    run_path.write_text(json.dumps(run, indent=2), encoding="utf-8")
    sys.exit(code)


if __name__ == "__main__":
    main()
