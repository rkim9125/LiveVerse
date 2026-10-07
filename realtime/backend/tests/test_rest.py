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
