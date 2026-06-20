from unittest.mock import patch

import pytest

from cito import pipeline


def test_generate_announcement_combines_sources():
    with patch("cito.pipeline.SOURCES", {
        "weather": _FakeSource("weather", "It is sunny."),
        "stocks": _FakeSource("stocks", "Apple up 1 percent."),
    }), patch("cito.pipeline.generate_script", side_effect=lambda frags: " | ".join(frags)):
        out = pipeline.generate_announcement(["weather", "stocks"])
    assert out == "It is sunny. | Apple up 1 percent."


def test_generate_announcement_skips_failing_source():
    with patch("cito.pipeline.SOURCES", {
        "weather": _FakeSource("weather", "It is sunny."),
        "stocks": _FailingSource(),
    }), patch("cito.pipeline.generate_script", side_effect=lambda frags: " | ".join(frags)):
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
    }), patch("cito.pipeline.generate_script", side_effect=lambda frags: " | ".join(frags)):
        out = pipeline.generate_announcement(["weather", "bogus"])
    assert out == "It is sunny."


def test_send_announcement_rejects_empty_text():
    with pytest.raises(ValueError):
        pipeline.send_announcement("   ")


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
