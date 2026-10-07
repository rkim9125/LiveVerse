#!/usr/bin/env python3
"""Put a browser capture on a recording's timeline.

The STT check page saves final segments with wall-clock times. A run file from
play_to_device.py says when playback started (t0) and where in the recording it
started (clip_start). Each segment becomes

    start = clip_start + (wall time - t0)

and the result is written next to the Whisper transcripts in the same shape
(segments with start, end, text), so eval/score.py can score it.

Usage (from realtime/backend):
    uv run python eval/capture_to_segments.py ~/Downloads/webspeech-capture-....json \\
        ~/liveverse-corpus/sermon-01/runs/20261008-201500.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def convert(capture: dict, run: dict) -> dict:
    t0, clip = run["t0"], run["clip_start"]
    end_limit = clip + run.get("duration", float("inf")) + 30  # recognition can lag the audio
    segments = []
    for s in capture["segments"]:
        start, end = clip + (s["start"] - t0), clip + (s["end"] - t0)
        if end < clip or start > end_limit:
            continue  # spoken before or long after this playback
        segments.append({"start": round(start, 2), "end": round(end, 2), "text": s["text"]})
    return {
        "source": capture.get("source", "webspeech"),
        "lang": capture.get("lang", "ko-KR"),
        "run": run.get("created"),
        "clip_start": clip,
        "duration": run.get("duration"),
        "stats": capture.get("stats", {}),
        "segments": segments,
    }


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("capture", type=Path)
    p.add_argument("run", type=Path)
    args = p.parse_args()
    capture = json.loads(args.capture.expanduser().read_text(encoding="utf-8"))
    run_path = args.run.expanduser()
    run = json.loads(run_path.read_text(encoding="utf-8"))
    out = convert(capture, run)
    sermon_dir = run_path.parent.parent
    dest = sermon_dir / f"webspeech.{run['created']}.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        f"wrote {dest.name}: {len(out['segments'])} segments, "
        f"{out['clip_start']:.0f} s to {out['clip_start'] + (out['duration'] or 0):.0f} s"
    )


if __name__ == "__main__":
    main()
