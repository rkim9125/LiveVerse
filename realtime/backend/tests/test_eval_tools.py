"""Evaluation tools for the speech input (stage 3), on synthetic data only."""

import importlib.util
import json
from pathlib import Path

import pytest

EVAL = Path(__file__).resolve().parents[1] / "eval"


def load(name):
    spec = importlib.util.spec_from_file_location(name, EVAL / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


play = load("play_to_device")
capture = load("capture_to_segments")
score = load("score")
latency = load("stt_latency")


def test_parse_devices_reads_audiotoolbox_listing():
    text = "\n".join(
        [
            "[AudioToolbox @ 0x1] CoreAudio devices:",
            "[AudioToolbox @ 0x1] [0]              BlackHole 2ch, BlackHole2ch_UID",
            "[AudioToolbox @ 0x1] [1]   MacBook Pro Speakers, BuiltInSpeakerDevice",
            "[AudioToolbox @ 0x1] [2]                 (null), unknown",
            "[out#0/audiotoolbox @ 0x2] Output file does not contain any stream",
        ]
    )
    assert play.parse_devices(text) == [(0, "BlackHole 2ch"), (1, "MacBook Pro Speakers")]


def test_densest_window_picks_the_busiest_ten_minutes():
    labels = [{"t_start": t, "correct_refs": ["jo 3:16"]} for t in (30, 700, 720, 760, 1290)]
    labels.append({"t_start": 100, "correct_refs": []})  # rejected, not gold
    start, n = play.densest_window(labels, length=600, step=60)
    assert n == 3 and start <= 700 and start + 600 > 760
    assert play.densest_window([], 600) == (0.0, 0)


def test_capture_is_put_on_the_recording_timeline():
    run = {"t0": 1000.0, "clip_start": 1320.0, "duration": 600.0, "created": "x"}
    cap = {
        "source": "webspeech",
        "lang": "ko-KR",
        "segments": [
            {"start": 990.0, "end": 995.0, "text": "before playback"},
            {"start": 1002.0, "end": 1004.5, "text": "요한복음 3장 16절"},
            {"start": 1700.0, "end": 1701.0, "text": "long after"},
        ],
    }
    out = capture.convert(cap, run)
    assert out["segments"] == [{"start": 1322.0, "end": 1324.5, "text": "요한복음 3장 16절"}]
    assert out["clip_start"] == 1320.0


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    d = tmp_path / "sermon-x"
    d.mkdir()
    labels = [
        {"id": "a", "t_start": 10, "t_end": 12, "correct_refs": ["jo 3:16"], "decision": "accept"},
        {
            "id": "b",
            "t_start": 200,
            "t_end": 202,
            "correct_refs": ["rm 8:28"],
            "decision": "accept",
        },
    ]
    (d / "candidates.jsonl").write_text("\n".join(json.dumps(c) for c in labels) + "\n")
    segments = [
        {"start": 6, "end": 8.5, "text": "요한복음 3장 16절 말씀입니다"},  # 1.5 s early
        {"start": 199, "end": 203, "text": "로마서 8장 28절을 보면"},
    ]
    (d / "webspeech.x.json").write_text(json.dumps({"segments": segments}))
    monkeypatch.setenv("LIVEVERSE_CORPUS", str(tmp_path))
    return d


def test_score_slack_and_range(corpus):
    tight = score.score_sermon("sermon-x", "webspeech.x.json", slack=1.0)
    loose = score.score_sermon("sermon-x", "webspeech.x.json", slack=5.0)
    assert tight["tp"] == 1 and loose["tp"] == 2
    part = score.score_sermon("sermon-x", "webspeech.x.json", t_from=100, t_to=300, slack=5.0)
    assert part["labels"] == 1 and part["tp"] == 1 and part["fp"] == 0


def test_gold_mentions_use_word_times():
    labels = [
        {"t_start": 100.0, "t_end": 125.0, "correct_refs": ["jo 3:16"]},
        {"t_start": 200.0, "t_end": 220.0, "correct_refs": ["rm 8:28"]},
        {"t_start": 300.0, "t_end": 310.0, "correct_refs": []},
    ]
    preds = [(108.0, 110.0, "jo 3:16"), (150.0, 151.0, "rm 8:28")]
    gold = latency.gold_mentions(labels, preds)
    assert gold == [
        {"refs": ["jo 3:16"], "end": 110.0, "approx": False},
        {"refs": ["rm 8:28"], "end": 220.0, "approx": True},
    ]


def test_latency_joins_gold_with_the_log():
    run = {"t0": 5000.0, "clip_start": 100.0, "duration": 600.0}
    gold = [
        {"refs": ["jo 3:16"], "end": 110.0, "approx": False},  # said at wall 5010
        {"refs": ["jo 3:16"], "end": 200.0, "approx": False},  # already on screen
        {"refs": ["rm 8:28"], "end": 300.0, "approx": False},  # never shown
        {"refs": ["gn 1:1"], "end": 50.0, "approx": False},  # before the clip
    ]
    records = [
        {
            "event": "segment",
            "conn": "c",
            "seq": 3,
            "t_client": 4011.0,
            "clock_offset": 1000.0,
            "t_recv": 5011.05,
            "t_sent": 5011.06,
            "shown": "jo 3:16",
        },
        {"event": "rendered", "conn": "c", "seq": 3, "t_render": 4011.1, "clock_offset": 1000.0},
        {
            "event": "segment",
            "conn": "c",
            "seq": 4,
            "t_recv": 5300.0,
            "t_sent": None,
            "shown": "jo 3:16",
        },
    ]
    out = latency.measure(gold, run, records)
    assert (out["gold"], out["already_shown"], out["matched"], out["missed"]) == (3, 1, 1, 1)
    h = out["hops"]
    assert h["stt"]["p50_ms"] == 1000 and h["server"]["p50_ms"] == 10
    assert h["render"]["p50_ms"] == 40 and h["total"]["max_ms"] == 1100
