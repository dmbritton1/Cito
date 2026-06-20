from unittest.mock import patch

import pytest

from cito.engine import clean, CleanedEmptyError, generate_script, template_fallback


def test_strips_surrounding_whitespace():
    assert clean("  Good morning team.  ") == "Good morning team."


def test_strips_wrapping_double_quotes():
    assert clean('"Good morning team."') == "Good morning team."


def test_strips_code_fences_and_backticks():
    assert clean("```\nGood morning team.\n```") == "Good morning team."
    assert clean("`Good morning team.`") == "Good morning team."


def test_strips_leading_preamble():
    assert clean("Here's your announcement: Good morning team.") == "Good morning team."
    assert clean("Sure! Here is the announcement:\nGood morning team.") == "Good morning team."


def test_drops_markdown_bullet_lines_keeps_prose():
    raw = (
        "*   Topic: Good-morning announcement.\n"
        "*   Tone: Friendly.\n"
        "Good morning, team, have a great day!"
    )
    assert clean(raw) == "Good morning, team, have a great day!"


def test_empty_after_cleaning_raises():
    with pytest.raises(CleanedEmptyError):
        clean("```\n```")


def test_too_long_raises():
    with pytest.raises(CleanedEmptyError):
        clean("word " * 400)


def test_template_fallback_joins_fragments():
    out = template_fallback(["It is 75 and sunny.", "The S&P 500 rose 1 percent."])
    assert "75 and sunny" in out
    assert "S&P 500 rose 1 percent" in out


def test_generate_script_uses_fallback_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    out = generate_script(["It is 75 and sunny."])
    assert "75 and sunny" in out


def test_generate_script_calls_gemma_and_cleans(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")

    class FakeResp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"candidates": [{"content": {"parts": [
                {"text": '"Good morning team, 75 and sunny today!"'}
            ]}}]}

    with patch("cito.engine.httpx.post", return_value=FakeResp()) as mock_post:
        out = generate_script(["It is 75 and sunny."])
    assert out == "Good morning team, 75 and sunny today!"
    assert mock_post.called


def test_generate_script_falls_back_on_gemma_error(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")

    def boom(*a, **k):
        raise RuntimeError("network down")

    with patch("cito.engine.httpx.post", side_effect=boom):
        out = generate_script(["It is 75 and sunny."])
    assert "75 and sunny" in out  # fell back to template


def test_cleans_real_gemma_multi_option_dump():
    raw = (
        "*   Topic: Good-morning office announcement.\n"
        "*   Tone: Friendly.\n"
        "\n"
        "*   \"Good morning everyone, let's have a great day!\" (generic)\n"
        "*   \"Rise and shine, team!\" (energetic)\n"
        "\n"
        "*Self-Correction:* The prompt asks for one sentence.\n"
        "\n"
        "\"Good morning team, let's make today a great one!\"\n"
        "\"Good morning team, let's make today a great one!\"\n"
    )
    assert clean(raw) == "Good morning team, let's make today a great one!"


def test_chatty_options_with_no_clean_answer_raises():
    raw = (
        "Sure! Here are a few options:\n\n"
        "*   \"Option one.\"\n"
        "*   \"Option two.\"\n\n"
        "Let me know which you prefer!"
    )
    with pytest.raises(CleanedEmptyError):
        clean(raw)


def test_extract_say_returns_single_tag():
    from cito.engine import extract_say
    assert extract_say("blah <say>Hello team.</say> blah") == "Hello team."


def test_extract_say_returns_last_of_multiple():
    from cito.engine import extract_say
    raw = "<say>example one</say> reasoning <say>the real answer</say>"
    assert extract_say(raw) == "the real answer"


def test_extract_say_spans_newlines():
    from cito.engine import extract_say
    assert extract_say("x\n<say>line one\nstill answer</say>\ny") == "line one\nstill answer"


def test_extract_say_returns_none_when_absent():
    from cito.engine import extract_say
    assert extract_say("just a reasoning dump, no tag") is None
