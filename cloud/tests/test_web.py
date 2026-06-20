from unittest.mock import patch

from fastapi.testclient import TestClient

from cito.web.app import app

client = TestClient(app)


def test_index_served():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Cito" in resp.text


def test_generate_endpoint():
    with patch("cito.web.app.pipeline.generate_announcement", return_value="It is sunny."):
        resp = client.post("/generate", json={"sources": ["weather"]})
    assert resp.status_code == 200
    assert resp.json() == {"text": "It is sunny."}


def test_send_endpoint():
    from cito.pipeline import SendResult
    with patch("cito.web.app.pipeline.send_announcement", return_value=SendResult(packets=5)):
        resp = client.post("/send", json={"text": "Hello team."})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "packets": 5}


def test_send_rejects_empty():
    resp = client.post("/send", json={"text": "   "})
    assert resp.status_code == 400


def test_get_config_returns_voice_and_presets(monkeypatch):
    from fastapi.testclient import TestClient
    from cito.web import app as webapp
    monkeypatch.setattr("cito.web.app.config.load_config", lambda: {"voice": "Hi.", "preset": "Friendly"})
    client = TestClient(webapp.app)
    body = client.get("/config").json()
    assert body["voice"] == "Hi."
    assert "Professional" in body["presets"]


def test_post_voice_saves_validated(monkeypatch):
    from fastapi.testclient import TestClient
    from cito.web import app as webapp
    saved = {}
    monkeypatch.setattr("cito.web.app.config.save_config",
                        lambda cfg: saved.update(cfg) or {"voice": cfg["voice"], "preset": cfg["preset"]})
    client = TestClient(webapp.app)
    r = client.post("/voice", json={"voice": "Be upbeat.", "preset": "Friendly"})
    assert r.status_code == 200
    assert saved["voice"] == "Be upbeat."


def test_post_preview_returns_sample(monkeypatch):
    from fastapi.testclient import TestClient
    from cito.web import app as webapp
    monkeypatch.setattr("cito.web.app.pipeline.generate_announcement",
                        lambda sources, voice=None: f"PREVIEW[{voice}]")
    client = TestClient(webapp.app)
    r = client.post("/preview", json={"sources": ["weather"], "voice": "Zany."})
    assert r.json()["text"] == "PREVIEW[Zany.]"
