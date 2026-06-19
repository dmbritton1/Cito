"""Confirm a Gemma REST round-trip (Phase 0 Check A).

Usage:  uv run python -m cito.spikes.gemma_check
Requires GEMINI_API_KEY in cloud/.env.
"""

import os
import sys

import httpx
from dotenv import load_dotenv

from cito.constants import GEMINI_ENDPOINT, GEMMA_MODEL


def main() -> None:
    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("GEMINI_API_KEY not set. Copy cloud/.env.example to cloud/.env and fill it in.")

    url = GEMINI_ENDPOINT.format(model=GEMMA_MODEL)
    resp = httpx.post(
        url,
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        json={"contents": [{"parts": [
            {"text": "Write one short, friendly good-morning office announcement sentence."}
        ]}]},
        timeout=30.0,
    )
    print(f"HTTP {resp.status_code}")
    resp.raise_for_status()

    data = resp.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    print(f"Gemma says: {text}")


if __name__ == "__main__":
    main()
