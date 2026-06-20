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
