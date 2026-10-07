import json

from app.core.latency import LatencyLog


def test_log_and_summary(tmp_path):
    log = LatencyLog(tmp_path)
    log.segment(
        "a",
        1,
        t_client=100.0,
        t_recv=100.5,
        t_detect_done=100.502,
        t_sent=100.503,
        clock_offset=0.4,
        shown_changed=True,
        shown="jo 3:16",
    )
    log.segment(
        "a",
        2,
        t_client=101.0,
        t_recv=101.5,
        t_detect_done=101.501,
        t_sent=None,
        clock_offset=0.4,
        shown_changed=False,
        shown="jo 3:16",
    )
    log.rendered("a", 1, t_render=100.2, clock_offset=0.4)
    s = log.summary()
    assert s["segments"] == 2
    assert s["detect"]["n"] == 2 and s["detect"]["max"] == 2.0
    assert s["client_to_server"]["p50"] == 100.0
    assert s["send_to_render"] == {"n": 1, "p50": 97.0, "p95": 97.0, "max": 97.0}
    assert s["speech_to_render"]["p50"] == 200.0


def test_no_text_is_written(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "ping", "t_client": 1.0})
        ws.receive_json()
        ws.send_json(
            {
                "type": "transcript",
                "seq": 7,
                "text": "요한복음 3장 16절 말씀입니다",
                "is_final": True,
                "t_client": 2.0,
            }
        )
        state = ws.receive_json()
        ws.send_json({"type": "rendered", "seq": 7, "t_render": 2.05})
        ws.send_json({"type": "ping", "t_client": 3.0})
        ws.receive_json()
    log = client.app.state.latency
    raw = log.path().read_text(encoding="utf-8")
    assert "요한복음" not in raw and "말씀" not in raw
    lines = [json.loads(line) for line in raw.splitlines()]
    seg = next(r for r in lines if r["event"] == "segment")
    assert seg["seq"] == 7 and seg["shown"] == "jo 3:16" and seg["t_sent"] == state["t_sent"]
    assert any(r["event"] == "rendered" for r in lines)
    summary = client.get("/api/metrics/latency").json()
    assert summary["segments"] == 1 and summary["send_to_render"]["n"] == 1
