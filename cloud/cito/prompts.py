"""Prompt assembly for the content engine.

Three layers (spec 3.3.1): a fixed envelope we own + an admin voice layer +
the runtime source data. The model is told to wrap its answer in <say>…</say>
so the engine can extract it and discard the model's reasoning.
"""

ENVELOPE = (
    "You are an office announcement writer. Read the INPUT and write one short, "
    "spoken office announcement (one to three sentences) to be read aloud by a "
    "text-to-speech voice. Use speech-friendly numbers (say 'twenty percent', not "
    "'20%') and spell out symbols. Output ONLY the final announcement wrapped in "
    "<say>...</say> tags, with nothing else inside the tags.\n"
)

# Few-shot examples teach the <say> format. Kept tone-light so the voice layer,
# not the examples, drives personality.
FEW_SHOT = (
    "INPUT: In Austin, it's Sunny with a high of 95 and a low of 70.\n"
    "<say>It's a sunny one in Austin today, topping out around ninety-five degrees.</say>\n\n"
    "INPUT: At today's market close: Apple up about 2 percent; Tesla down about 3 percent.\n"
    "<say>At the close, Apple rose about two percent while Tesla slipped around three percent.</say>\n\n"
)


def assemble_prompt(fragments: list[str], voice: str = "") -> str:
    """Concatenate envelope + optional voice guidance + few-shot + the INPUT data."""
    parts = [ENVELOPE]
    if voice.strip():
        parts.append(
            "\nHouse style (follow unless it conflicts with the rules above): "
            f"{voice.strip()}\n"
        )
    parts.append("\n" + FEW_SHOT)
    body = " ".join(f.strip() for f in fragments if f.strip())
    parts.append(f"INPUT: {body}\n")
    return "".join(parts)
