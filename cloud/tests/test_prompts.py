from cito.prompts import ENVELOPE, assemble_prompt


def test_prompt_includes_envelope_and_say_contract():
    p = assemble_prompt(["In Austin, it's Sunny with a high of 95."], voice="")
    assert ENVELOPE.split("\n")[0] in p
    assert "<say>" in p  # the few-shot examples demonstrate the tag


def test_prompt_includes_fragment_as_input():
    p = assemble_prompt(["In Austin, it's Sunny with a high of 95."], voice="")
    assert "INPUT:" in p
    assert "In Austin, it's Sunny with a high of 95." in p


def test_prompt_includes_voice_when_provided():
    p = assemble_prompt(["data"], voice="Be very upbeat and casual.")
    assert "Be very upbeat and casual." in p


def test_prompt_omits_voice_section_when_blank():
    p = assemble_prompt(["data"], voice="   ")
    assert "House style" not in p


def test_prompt_joins_multiple_fragments_into_one_input():
    p = assemble_prompt(["Weather line.", "Market line."], voice="")
    assert "Weather line. Market line." in p
