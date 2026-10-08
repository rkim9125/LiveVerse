import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import create_app


def final(ws, seq, text):
    ws.send_json({"type": "transcript", "seq": seq, "text": text, "is_final": True, "t_client": 0})


def test_initial_state_then_final_segment(client):
    with client.websocket_connect("/ws") as ws:
        first = ws.receive_json()
        assert first["type"] == "state" and first["shown"] is None
        final(ws, 1, "요한복음 3장 16절 말씀입니다")
        state = ws.receive_json()
        assert state["seq"] == 1
        assert state["shown"]["ref"] == "jo 3:16"
        assert state["shown"]["source"] == "rule"
        assert state["shown"]["verses"][0]["en"].startswith("For God so loved")
        assert state["t_recv"] <= state["t_sent"]


def test_one_interim_gives_preview_only(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "transcript", "seq": 1, "text": "로마서 8장 28절", "is_final": False})
        preview = ws.receive_json()
        assert preview["type"] == "preview"
        assert [c["ref"] for c in preview["candidates"]] == ["rm 8:28"]
    assert client.get("/api/session").json()["shown"] is None


def test_no_state_when_nothing_changes(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        final(ws, 1, "오늘도 함께 모였습니다")
        ws.send_json({"type": "ping", "t_client": 1.0})
        assert ws.receive_json()["type"] == "pong"  # no state came first


def test_switch_search_clear(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        final(ws, 1, "로마서 8장 28절과 요한복음 3장 16절")
        state = ws.receive_json()
        alt = next(a for a in state["alternatives"] if a["ref"] == "rm 8:28")
        ws.send_json({"type": "switch", "candidate_id": alt["id"]})
        state = ws.receive_json()
        assert (state["shown"]["ref"], state["shown"]["manual"]) == ("rm 8:28", True)
        ws.send_json({"type": "search", "query": "matthew 22:1-14"})
        state = ws.receive_json()
        assert (state["shown"]["ref"], state["shown"]["source"]) == ("mt 22:1-14", "manual")
        ws.send_json({"type": "clear"})
        assert ws.receive_json()["shown"] is None


def test_errors(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "search", "query": "nowhere 1:1"})
        assert ws.receive_json()["type"] == "error"
        ws.send_json({"type": "switch", "candidate_id": "c999"})
        assert ws.receive_json()["type"] == "error"
        ws.send_json({"type": "transcript", "text": "no seq"})
        assert ws.receive_json()["type"] == "error"
        ws.send_json({"type": "dance"})
        assert "unknown" in ws.receive_json()["message"]
        ws.send_text("not json")
        assert ws.receive_json()["type"] == "error"


def test_state_goes_to_every_screen(client):
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        a.receive_json()
        b.receive_json()
        final(a, 1, "요한복음 3장 16절")
        assert a.receive_json()["shown"]["ref"] == "jo 3:16"
        assert b.receive_json()["shown"]["ref"] == "jo 3:16"


def test_remote_socket_is_refused(settings, store):
    remote = TestClient(create_app(settings, store), client=("10.0.0.5", 50000))
    with pytest.raises(WebSocketDisconnect):
        with remote.websocket_connect("/ws") as ws:
            ws.receive_json()


def interim(ws, seq, text):
    ws.send_json({"type": "transcript", "seq": seq, "text": text, "is_final": False, "t_client": 0})


def test_stable_interim_shows_marked_then_final_confirms(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        interim(ws, 1, "로마서 8장 28절")
        assert ws.receive_json()["type"] == "preview"
        interim(ws, 1, "로마서 8장 28절 말씀")
        state = ws.receive_json()
        assert state["type"] == "state" and state["from_interim"] is True
        assert (state["shown"]["ref"], state["shown"]["interim"]) == ("rm 8:28", True)
        assert ws.receive_json()["type"] == "preview"
        final(ws, 1, "로마서 8장 28절 말씀입니다")
        state = ws.receive_json()
        assert state["from_interim"] is False
        assert (state["shown"]["ref"], state["shown"]["interim"]) == ("rm 8:28", False)


def test_interim_held_without_new_results_is_shown(settings, store):
    from dataclasses import replace

    client = TestClient(create_app(replace(settings, interim_hold_s=0.05), store))
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        interim(ws, 1, "로마서 8장 28절")
        assert ws.receive_json()["type"] == "preview"
        state = ws.receive_json()  # from the hold timer
        assert state["from_interim"] is True and state["shown"]["interim"] is True
        ws.send_json({"type": "rendered", "seq": 1, "t_render": 1.0, "from_interim": True})
    summary = client.get("/api/metrics/latency").json()
    assert summary["segments"] == 1
