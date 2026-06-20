"""Content engine: turn structured source data into a clean spoken script.

LLM output is untrusted text until cleaned. `clean()` strips wrappers, preambles,
and markdown so phones never speak "Here's your announcement:" or asterisks.
"""

import os
import re

import httpx

from cito.constants import GEMINI_ENDPOINT, GEMMA_MODEL

MAX_CHARS = 600  # a spoken announcement is short; longer => model misbehaved

_PREAMBLE_RE = re.compile(
    r"^\s*(sure[!,. ]*)?(here(?:'s| is)[^:]*:)\s*",
    re.IGNORECASE,
)


class CleanedEmptyError(ValueError):
    """Raised when cleaning leaves nothing announceable (caller should fall back)."""


def clean(raw: str) -> str:
    text = raw.strip()

    # Remove wrapping code fences / backticks.
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    text = text.strip("`").strip()

    # Remove a single layer of wrapping quotes.
    if len(text) >= 2 and text[0] in "\"'" and text[-1] == text[0]:
        text = text[1:-1].strip()

    # Strip a leading "Here's your announcement:" style preamble.
    text = _PREAMBLE_RE.sub("", text).strip()

    # Drop markdown bullet / list lines (*, -, +, or "1.") — keep prose lines.
    kept = [
        ln for ln in text.splitlines()
        if not re.match(r"^\s*([*\-+]|\d+\.)\s+", ln)
    ]
    text = "\n".join(kept).strip()

    # Collapse internal whitespace runs to single spaces.
    text = re.sub(r"\s+", " ", text).strip()

    if not text:
        raise CleanedEmptyError("nothing announceable after cleaning")
    if len(text) > MAX_CHARS:
        raise CleanedEmptyError(f"cleaned output too long ({len(text)} chars)")
    return text


ENVELOPE = (
    "You write a single short spoken office announcement to be read aloud by a "
    "text-to-speech voice. Return ONLY the announcement text: no preamble, no "
    "markdown, no quotes, no lists, no options, no commentary. Keep it to one to "
    "three friendly sentences. Use speech-friendly numbers and spell out symbols.\n\n"
    "Here is the information to announce:\n"
)


def template_fallback(prompt_fragments: list[str]) -> str:
    """Deterministic, no-AI announcement built straight from the source fragments."""
    body = " ".join(f.strip() for f in prompt_fragments if f.strip())
    return f"Good morning everyone. {body}".strip()


def _call_gemma(prompt: str, api_key: str) -> str:
    url = GEMINI_ENDPOINT.format(model=GEMMA_MODEL)
    resp = httpx.post(
        url,
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=30.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def generate_script(prompt_fragments: list[str]) -> str:
    """Assemble the layered prompt, call Gemma, and clean — falling back on any failure."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return template_fallback(prompt_fragments)

    prompt = ENVELOPE + "\n".join(prompt_fragments)
    try:
        raw = _call_gemma(prompt, api_key)
        return clean(raw)
    except (httpx.HTTPError, CleanedEmptyError, KeyError, RuntimeError):
        return template_fallback(prompt_fragments)
