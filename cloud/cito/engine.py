"""Content engine: turn structured source data into a clean spoken script.

LLM output is untrusted text until cleaned. `clean()` strips wrappers, preambles,
and markdown so phones never speak "Here's your announcement:" or asterisks.
"""

import os
import re

import httpx

from cito.constants import GEMINI_ENDPOINT, GEMMA_MODEL

MAX_CHARS = 600  # a spoken announcement is short; longer => model misbehaved
RAW_MAX_CHARS = 800  # raw model output longer than this is a reasoning dump, not an announcement

_PREAMBLE_RE = re.compile(
    r"^\s*(?:sure|okay|certainly)?[!,.\s]*"
    r"here(?:'s| is| are)\b[^:\n]{0,40}"
    r"(?:announcement|forecast|update|summary|message|options?|following)[^:\n]*:\s*",
    re.IGNORECASE,
)

_META_LABEL_RE = re.compile(
    r"^\s*\*?\s*(Topic|Tone|Length|Self[- ]?Correction|Note|Draft|Final Answer|Option\s+[A-Za-z0-9]+)\b[^:]*:",
    re.IGNORECASE,
)

_SIGN_OFF_PHRASES = ("let me know", "which you prefer", "hope this helps", "feel free")

_INLINE_MD_RE = re.compile(r"[*_]|^[#>]+\s*", re.MULTILINE)

_SAY_RE = re.compile(r"<say>(.*?)</say>", re.DOTALL | re.IGNORECASE)


class CleanedEmptyError(ValueError):
    """Raised when cleaning leaves nothing announceable (caller should fall back)."""


def clean(raw: str) -> str:
    # Step 0: reject a reasoning dump outright. A clean 1-3 sentence announcement is
    # short; output this long is the model thinking out loud, not an announcement.
    if len(raw.strip()) > RAW_MAX_CHARS:
        raise CleanedEmptyError(f"raw output too long, likely a reasoning dump ({len(raw)} chars)")

    # Step 1: strip surrounding whitespace.
    text = raw.strip()

    # Step 2: strip wrapping code fences / backticks.
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    text = text.strip("`").strip()

    # Step 3: strip a leading assistant preamble when it contains an assistant-y noun.
    text = _PREAMBLE_RE.sub("", text).strip()

    # Step 4: process lines — drop blank, bullet/list, meta-label, and sign-off lines.
    kept = []
    for line in text.splitlines():
        # Drop blank/whitespace-only.
        if not line.strip():
            continue
        # Drop bullet / numbered list lines.
        if re.match(r"^\s*([*\-+]|\d+\.)\s+", line):
            continue
        # Drop meta-label lines (e.g. "* Topic:", "Tone:", "Self-Correction:").
        if _META_LABEL_RE.match(line):
            continue
        # Drop assistant sign-off lines.
        lower = line.lower()
        if any(phrase in lower for phrase in _SIGN_OFF_PHRASES):
            continue
        kept.append(line)

    # Step 5: strip inline markdown emphasis and leading # / > from surviving lines,
    # then strip a single layer of wrapping quotes on each line.
    cleaned_lines = []
    for line in kept:
        line = re.sub(r"[*_]", "", line)
        line = re.sub(r"^[#>]+\s*", "", line).strip()
        # Strip a single layer of wrapping quotes on this line.
        if len(line) >= 2 and line[0] in "\"'" and line[-1] == line[0]:
            line = line[1:-1].strip()
        if line:
            cleaned_lines.append(line)

    # Step 6: deduplicate identical consecutive lines.
    deduped = []
    for line in cleaned_lines:
        if not deduped or line != deduped[-1]:
            deduped.append(line)

    # Step 7: join with a single space, then collapse internal whitespace.
    text = " ".join(deduped)
    text = re.sub(r"\s+", " ", text).strip()

    # Step 8: strip a single layer of wrapping quotes on the whole result.
    if len(text) >= 2 and text[0] in "\"'" and text[-1] == text[0]:
        text = text[1:-1].strip()

    # Step 9: validate.
    if not text:
        raise CleanedEmptyError("nothing announceable after cleaning")
    if len(text) > MAX_CHARS:
        raise CleanedEmptyError(f"cleaned output too long ({len(text)} chars)")
    return text


def extract_say(raw: str) -> str | None:
    """Return the content of the LAST <say>…</say> block, or None if absent.

    The model emits its reasoning plus a final answer wrapped in <say> tags
    (and may echo the few-shot example tags first), so the last block is the
    real answer.
    """
    matches = _SAY_RE.findall(raw)
    if not matches:
        return None
    return matches[-1].strip()


ENVELOPE = (
    "You write one short spoken office announcement to be read aloud by a "
    "text-to-speech voice. Output rules: respond with the announcement sentence(s) "
    "ONLY — nothing before or after. Do NOT show your reasoning, goals, constraints, "
    "drafts, or multiple options. Do NOT use markdown, asterisks, bullet points, "
    "quotation marks, or headings. One to three friendly sentences. Use "
    "speech-friendly numbers (say 'twenty percent', not '20%') and spell out symbols.\n\n"
    "Information to announce:\n"
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
        timeout=60.0,
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
