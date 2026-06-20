"""Content engine: turn structured source data into a clean spoken script.

LLM output is untrusted text until cleaned. `clean()` strips wrappers, preambles,
and markdown so phones never speak "Here's your announcement:" or asterisks.
"""

import re

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
