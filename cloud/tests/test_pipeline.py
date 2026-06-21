from unittest.mock import patch

import pytest

from cito import pipeline


def test_generate_announcement_combines_sources():
    with patch("cito.pipeline.SOURCES", {
        "weather": _FakeSource("weather", "It is sunny."),
        "stocks": _FakeSource("stocks", "Apple up 1 percent."),
    }), patch("cito.pipeline.generate_script", side_effect=lambda frags, voice="": " | ".join(frags)):
        out = pipeline.generate_announcement(["weather", "stocks"])
    assert out == "It is sunny. | Apple up 1 percent."


def test_generate_announcement_skips_failing_source():
    with patch("cito.pipeline.SOURCES", {
        "weather": _FakeSource("weather", "It is sunny."),
        "stocks": _FailingSource(),
    }), patch("cito.pipeline.generate_script", side_effect=lambda frags, voice="": " | ".join(frags)):
        out = pipeline.generate_announcement(["weather", "stocks"])
    assert out == "It is sunny."


def test_send_announcement_wires_tts_encode_delivery():
    calls = {}

    def fake_tts(text):
        calls["tts"] = text
        return "a.mp3"

    with patch("cito.pipeline.tts.synthesize", side_effect=fake_tts), \
         patch("cito.pipeline.audio.encode_mulaw", return_value="a.ulaw"), \
         patch("cito.pipeline.MulticastRTPSender") as sender_cls:
        sender_cls.return_value.send.return_value = 42
        result = pipeline.send_announcement("Hello team.")
    assert calls["tts"] == "Hello team."
    assert result.packets == 42


def test_generate_announcement_skips_unknown_key():
    with patch("cito.pipeline.SOURCES", {
        "weather": _FakeSource("weather", "It is sunny."),
    }), patch("cito.pipeline.generate_script", side_effect=lambda frags, voice="": " | ".join(frags)):
        out = pipeline.generate_announcement(["weather", "bogus"])
    assert out == "It is sunny."


def test_send_announcement_rejects_empty_text():
    with pytest.raises(ValueError):
        pipeline.send_announcement("   ")


def test_generate_announcement_uses_explicit_voice(monkeypatch):
    captured = {}

    def fake_generate_script(fragments, voice=""):
        captured["voice"] = voice
        return "ok"

    monkeypatch.setattr("cito.pipeline.SOURCES", {"weather": _FakeSource("weather", "sunny")})
    monkeypatch.setattr("cito.pipeline.generate_script", fake_generate_script)
    from cito import pipeline
    pipeline.generate_announcement(["weather"], voice="Be terse.")
    assert captured["voice"] == "Be terse."


def test_generate_announcement_loads_saved_voice_when_none(monkeypatch):
    captured = {}

    def fake_generate_script(fragments, voice=""):
        captured["voice"] = voice
        return "ok"

    monkeypatch.setattr("cito.pipeline.SOURCES", {"weather": _FakeSource("weather", "sunny")})
    monkeypatch.setattr("cito.pipeline.generate_script", fake_generate_script)
    monkeypatch.setattr("cito.pipeline.config.load_config", lambda: {"voice": "Saved voice.", "preset": "Friendly"})
    from cito import pipeline
    pipeline.generate_announcement(["weather"])
    assert captured["voice"] == "Saved voice."


class _FakeSource:
    def __init__(self, name, fragment):
        self.name = name
        self._fragment = fragment

    def fetch(self):
        return {}

    def prompt_fragment(self, data):
        return self._fragment


class _FailingSource:
    name = "stocks"

    def fetch(self):
        raise RuntimeError("provider down")

    def prompt_fragment(self, data):
        return "unused"


def test_generate_announcement_appends_document_fragment(monkeypatch):
    captured = {}

    def fake_generate_script(fragments, voice=""):
        captured["fragments"] = fragments
        return "ok"

    monkeypatch.setattr("cito.pipeline.SOURCES", {})
    monkeypatch.setattr("cito.pipeline.generate_script", fake_generate_script)
    monkeypatch.setattr("cito.pipeline.config.load_config", lambda: {"voice": "", "preset": "Friendly"})
    from cito import pipeline
    pipeline.generate_announcement([], document_text="Quarterly memo body.")
    assert any("Quarterly memo body." in f for f in captured["fragments"])


def test_generate_announcement_ignores_blank_document(monkeypatch):
    captured = {}

    def fake_generate_script(fragments, voice=""):
        captured["fragments"] = fragments
        return "ok"

    monkeypatch.setattr("cito.pipeline.SOURCES", {})
    monkeypatch.setattr("cito.pipeline.generate_script", fake_generate_script)
    monkeypatch.setattr("cito.pipeline.config.load_config", lambda: {"voice": "", "preset": "Friendly"})
    from cito import pipeline
    pipeline.generate_announcement([], document_text="   ")
    assert captured["fragments"] == []


def test_send_uses_agent_when_connected(monkeypatch, tmp_path):
    from cito import pipeline
    ulaw = tmp_path / "out.ulaw"
    ulaw.write_bytes(b"\xff" * 320)  # 2 packets
    monkeypatch.setattr("cito.pipeline.tts.synthesize", lambda text: "out.mp3")
    monkeypatch.setattr("cito.pipeline.audio.encode_mulaw", lambda mp3: ulaw)
    monkeypatch.setattr("cito.pipeline.agent_link.deliver", lambda p, a, port: True)
    monkeypatch.setattr("cito.pipeline.MulticastRTPSender",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not send locally")))
    result = pipeline.send_announcement("hello")
    assert result.packets == 2  # computed from the µ-law length, not the local sender


def test_send_falls_back_to_local_without_agent(monkeypatch, tmp_path):
    from cito import pipeline
    ulaw = tmp_path / "out.ulaw"
    ulaw.write_bytes(b"\xff" * 160)
    monkeypatch.setattr("cito.pipeline.tts.synthesize", lambda text: "out.mp3")
    monkeypatch.setattr("cito.pipeline.audio.encode_mulaw", lambda mp3: ulaw)
    monkeypatch.setattr("cito.pipeline.agent_link.deliver", lambda p, a, port: False)

    class FakeSender:
        def send(self, path):
            return 7

    monkeypatch.setattr("cito.pipeline.MulticastRTPSender", lambda *a, **k: FakeSender())
    result = pipeline.send_announcement("hello")
    assert result.packets == 7  # local sender's count
