#!/usr/bin/env python3
"""Replay a transcript into a running backend over the WebSocket.

Sends each segment as a final transcript, with its time in the recording as
t_audio, and prints every screen change (time, reference, source, confidence).
Transcript text is never printed.

Usage (from realtime/backend, with the server running):
    uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
    uv run python eval/replay.py ~/liveverse-corpus/sermon-01/whisper.prompted.json
    uv run python eval/replay.py FILE --speed 1      # real time
    uv run python eval/replay.py FILE --speed 0      # as fast as possible (default)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

import websockets


def fmt(t: float) -> str:
    m, s = divmod(int(t), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}"


async def replay(path: Path, url: str, speed: float) -> None:
    segments = json.loads(path.read_text(encoding="utf-8"))["segments"]
    shown = None
    changes = 0
    async with websockets.connect(url) as ws:
        await ws.recv()  # initial state
        for _ in range(5):  # clock offset samples while the server is idle
            await ws.send(json.dumps({"type": "ping", "t_client": time.time()}))
            await ws.recv()
        start_wall, start_audio = time.time(), segments[0]["start"] if segments else 0
        for seq, seg in enumerate(segments, 1):
            if speed > 0:
                due = start_wall + (seg["start"] - start_audio) / speed
                await asyncio.sleep(max(0.0, due - time.time()))
            await ws.send(
                json.dumps(
                    {
                        "type": "transcript",
                        "seq": seq,
                        "text": seg["text"],
                        "is_final": True,
                        "t_audio": seg["start"],
                        "t_client": time.time(),
                    }
                )
            )
            await ws.send(json.dumps({"type": "ping", "t_client": time.time()}))
            while True:
                msg = json.loads(await ws.recv())
                if msg["type"] == "pong":
                    break
                if msg["type"] != "state":
                    continue
                await ws.send(json.dumps({"type": "rendered", "seq": seq, "t_render": time.time()}))
                now = msg["shown"]
                key = (now or {}).get("ref")
                if key != shown:
                    shown, changes = key, changes + 1
                    if now:
                        print(
                            f"{fmt(seg['start'])}  {now['ref']:<14} {now['source']:<8} "
                            f"{now['confidence']}"
                        )
                    else:
                        print(f"{fmt(seg['start'])}  (cleared)")
    print(f"{len(segments)} segments, {changes} screen changes")


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("transcript", type=Path)
    p.add_argument("--url", default="ws://127.0.0.1:8000/ws")
    p.add_argument("--speed", type=float, default=0.0, help="1 = real time, 0 = no waiting")
    args = p.parse_args()
    asyncio.run(replay(args.transcript.expanduser(), args.url, args.speed))


if __name__ == "__main__":
    main()
