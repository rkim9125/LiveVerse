"""Replay transcripts through the WebSocket, as the screen would receive them."""

import json
import os
from pathlib import Path

import pytest

FIXTURE = Path(__file__).with_name("fixtures") / "replay_kjv.jsonl"
CORPUS = Path(os.environ.get("LIVEVERSE_CORPUS", "~/liveverse-corpus")).expanduser()


def replay(client, segments):
    """Send final segments in order; return what the screen showed after each."""
    shown = None
    seen = []
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        for seq, (t_audio, text) in enumerate(segments, 1):
            ws.send_json(
                {
                    "type": "transcript",
                    "seq": seq,
                    "text": text,
                    "is_final": True,
                    "t_audio": t_audio,
                }
            )
            ws.send_json({"type": "ping", "t_client": 0})  # a reply marks the end of this segment
            while True:
                msg = ws.receive_json()
                if msg["type"] == "state":
                    shown = msg["shown"]
                elif msg["type"] == "pong":
                    break
            seen.append((shown["ref"], shown["source"]) if shown else (None, None))
    return seen


def test_synthetic_sermon(client):
    rows = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines()]
    seen = replay(client, [(r["t_audio"], r["text"]) for r in rows])
    expected = [(r["expect_shown"], r["expect_source"]) for r in rows]
    for i, (got, want) in enumerate(zip(seen, expected, strict=True)):
        assert got == want, f"segment {i + 1}: {rows[i]['text']!r}"


@pytest.mark.skipif(not (CORPUS / "sermon-01" / "whisper.json").exists(), reason="no local corpus")
@pytest.mark.parametrize("sermon", ["sermon-01", "sermon-02"])
def test_dev_transcript_replay(client, sermon):
    """Local only: a whole dev-set sermon through the socket. Prints counts, never text."""
    segments = json.loads((CORPUS / sermon / "whisper.prompted.json").read_text(encoding="utf-8"))
    segments = [(s["start"], s["text"]) for s in segments["segments"]]
    seen = replay(client, segments)
    changes = sum(1 for a, b in zip([(None, None), *seen[:-1]], seen, strict=True) if a != b)
    summary = client.get("/api/metrics/latency").json()
    detect_ms = summary["detect"]
    print(f"\n{sermon}: {len(segments)} segments, {changes} screen changes, detect {detect_ms}")
    assert changes > 10
    assert summary["detect"]["p95"] < 50


def test_replay_timing_uses_audio_clock(client):
    """A chapter said in passing must still wait 10 s of audio, however fast we replay."""
    seen = replay(client, [(0, "로마서 8장에 보면"), (30, "같이 읽겠습니다")])
    assert seen == [(None, None), (None, None)]
