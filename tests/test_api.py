import struct
import pytest
from fastapi.testclient import TestClient
from fakes import FakeBundle
from vietvoice.app import create_app
from vietvoice.config import Settings

KEY = "test-only-secret-" * 3


@pytest.fixture
def client(tmp_path):
    cfg = Settings(app_key=KEY, database_url=f"sqlite:///{tmp_path}/test.db", startup_models=True)
    with TestClient(create_app(cfg, bundle_factory=FakeBundle)) as c:
        yield c


def login(c):
    assert c.post("/api/login", json={"key":KEY}).status_code == 200


def start(ws):
    ws.send_json({"type":"start", "sample_rate":16000, "encoding":"pcm_s16le"})
    event = ws.receive_json()
    assert event["type"] == "started"
    return event["session_id"]


def until(ws, kind):
    events = []
    while True:
        event = ws.receive_json()
        events.append(event)
        if event["type"] == kind:
            return events


def test_auth_and_origin(client):
    assert client.get("/api/sessions").status_code == 401
    assert client.post("/api/login", json={"key":"bad"}).status_code == 401
    assert client.post("/api/login", json={"key":KEY}, headers={"Origin":"https://evil.example"}).status_code == 403
    response = client.post("/api/login", json={"key":KEY})
    assert "HttpOnly" in response.headers["set-cookie"]
    assert client.get("/health/ready").status_code == 200


def test_duplicate_rename_export(client):
    login(client)
    with client.websocket_connect("/api/stream") as ws:
        sid = start(ws)
        packet = struct.pack("<I", 0) + bytes(3200)
        ws.send_bytes(packet)
        until(ws, "ack")
        ws.send_bytes(packet)
        assert ws.receive_json()["duplicate"] is True
        ws.send_json({"type":"end"})
        assert until(ws, "done")[-1]["audio_seconds"] == 0.1
    s = client.get(f"/api/sessions/{sid}").json()
    assert len(s["segments"]) == 1 and s["status"] == "completed"
    assert client.put(f"/api/sessions/{sid}/speakers/speaker_1", json={"name":"Bác sĩ An"}).status_code == 200
    assert "Bác sĩ An" in client.get(f"/api/sessions/{sid}/export/txt").text
    assert "00:00:00,000 -->" in client.get(f"/api/sessions/{sid}/export/srt").text


def test_gap_stops_without_silent_loss(client):
    login(client)
    with client.websocket_connect("/api/stream") as ws:
        sid = start(ws)
        ws.send_bytes(struct.pack("<I", 2) + bytes(3200))
        assert ws.receive_json()["type"] == "error"
        assert until(ws, "done")[-1]["status"] == "interrupted"
    assert client.get(f"/api/sessions/{sid}").json()["duration"] == 0


def test_session_limit_and_release(client):
    login(client)
    with client.websocket_connect("/api/stream") as a:
        start(a)
        with client.websocket_connect("/api/stream") as b:
            assert b.receive_json()["code"] == "not_ready"
        a.send_json({"type":"end"})
        until(a, "done")
    assert client.get("/api/status").json()["active_sessions"] == 0


def test_missing_models_no_fake_results(tmp_path):
    def broken(settings):
        raise FileNotFoundError("missing model")
    cfg = Settings(app_key=KEY, database_url=f"sqlite:///{tmp_path}/test.db")
    with TestClient(create_app(cfg, bundle_factory=broken)) as c:
        assert c.get("/health/ready").status_code == 503
        login(c)
        with c.websocket_connect("/api/stream") as ws:
            assert ws.receive_json()["code"] == "not_ready"
