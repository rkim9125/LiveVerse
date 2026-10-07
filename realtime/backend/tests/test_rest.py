from fastapi.testclient import TestClient

from app.main import create_app


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["data"]["file"] == "kjv.js"
    assert body["quote_search"] is True
    assert body["show_threshold"] == 0.7
    assert body["detector"]


def test_verses_many_formats(client):
    for q in ["John 3:16-17", "jo 3:16-17", "요 3:16-17", "요한복음 3장 16절부터 17절까지"]:
        body = client.get("/api/verses", params={"ref": q}).json()
        assert body["ref"] == "jo 3:16-17", q
        assert [v["num"] for v in body["verses"]] == [16, 17]
        assert body["label"]["en"] == "John 3:16-17"


def test_verses_bad_input(client):
    r = client.get("/api/verses", params={"ref": "nowhere 1:1"})
    assert r.status_code == 400
    assert "write it like" in r.json()["detail"]


def test_remote_clients_are_refused(settings, store):
    remote = TestClient(create_app(settings, store), client=("10.0.0.5", 50000))
    assert remote.get("/api/health").status_code == 403


def test_detect_matches_the_pipeline(client):
    from app.detect.pipeline import detect
    from tests.fixtures import load_cases

    for case in load_cases()[:40]:
        body = client.post(
            "/api/detect",
            json={"text": case["input"], "mode": case["mode"], "spoken": case["context"]},
        ).json()
        direct = detect(case["input"], mode=case["mode"], context=case["context"])
        assert [m["ref"] for m in body["mentions"]] == [str(m.ref) for m in direct], case["id"]


def test_detect_sources_and_quote(client):
    body = client.post("/api/detect", json={"text": "다음 절", "spoken": "jo 3:16"}).json()
    assert body["mentions"][0]["source"] == "context"
    quote = "for God so loved the world, that he gave his only begotten Son"
    body = client.post("/api/detect", json={"text": quote}).json()
    assert body["quote"] == {"ref": "jo 3:16", "source": "quote", "confidence": 0.7}


def test_detect_bad_input(client):
    assert client.post("/api/detect", json={"text": "x", "mode": "loud"}).status_code == 400
    assert client.post("/api/detect", json={"text": "x", "spoken": "??"}).status_code == 400


def test_session_endpoints(client):
    assert client.get("/api/session").json()["shown"] is None
    assert client.post("/api/session/reset").json()["status"] == "reset"


def test_frontend_is_served(client):
    r = client.get("/ui/shared/speech.js")
    assert r.status_code == 200
    assert "WebSpeechSource" in r.text
