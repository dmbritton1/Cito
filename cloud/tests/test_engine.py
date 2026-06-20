import pytest

from cito.engine import clean, CleanedEmptyError


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
