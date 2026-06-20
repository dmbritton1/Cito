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
