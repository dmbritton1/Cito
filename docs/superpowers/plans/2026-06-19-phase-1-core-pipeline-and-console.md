# Phase 1 — Core Pipeline + Dev Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an end-to-end content pipeline (real data → Gemma → cleaned text → gTTS → µ-law → RTP) behind a headless engine that both a CLI and a one-page FastAPI console drive, with weather + stocks sources proving the pluggable design.

**Architecture:** A `Source` interface (`fetch() -> dict` + `prompt_fragment`) feeds a content `engine` that assembles a layered prompt, calls Gemma, and defensively `clean()`s the output (with a no-AI template fallback). A `pipeline` module exposes `generate_announcement(sources)` and `send_announcement(text)`; the CLI (`run.py`) and FastAPI app (`web/app.py`) are thin shells over it. Delivery reuses the Phase 0 `cito.rtp` packetizer via a `MulticastRTPSender`.

**Tech Stack:** Python 3.11+ (uv), httpx, gTTS, yfinance, fastapi, uvicorn, ffmpeg (CLI), pytest, ruff.

---

## File Structure

```
cloud/
  pyproject.toml                  # MODIFY: add fastapi, uvicorn, yfinance
  cito/
    constants.py                  # (exists) Gemini endpoint + model
    rtp.py                        # (exists) pure packetizer — reused
    engine.py                     # NEW: clean(), generate_script(), template fallback
    tts.py                        # NEW: synthesize(text) -> Path (gTTS)
    audio.py                      # NEW: encode_mulaw(path) -> Path (ffmpeg)
    delivery.py                   # NEW: MulticastRTPSender
    pipeline.py                   # NEW: generate_announcement(), send_announcement()
    run.py                        # NEW: CLI entry (announce ...)
    sources/
      __init__.py                 # NEW: SOURCES registry
      base.py                     # NEW: Source protocol
      weather.py                  # NEW: wttr.in fetcher + fragment
      stocks.py                   # NEW: yfinance fetcher + fragment
    web/
      __init__.py                 # NEW
      app.py                      # NEW: FastAPI routes
      index.html                  # NEW: one-page console
  tests/
    test_rtp_packet.py            # (exists)
    test_engine.py                # NEW: clean() + fallback + generate_script
    test_sources.py               # NEW: weather + stocks fetch shape
    test_pipeline.py              # NEW: generate/send with mocks
    test_web.py                   # NEW: FastAPI TestClient
```

All commands run from `cloud/` (the plan uses `uv --directory cloud run ...` so they work from the repo root too). The repo is on `main`; create a feature branch before Task 1 (the execution skill handles this).

---

## Task 1: Add dependencies

**Files:**
- Modify: `cloud/pyproject.toml`

- [ ] **Step 1: Add the runtime deps to `[project].dependencies`**

Edit `cloud/pyproject.toml` so the `dependencies` array reads exactly:
```toml
dependencies = [
    "httpx",
    "python-dotenv",
    "gTTS",
    "yfinance",
    "fastapi",
    "uvicorn",
]
```

- [ ] **Step 2: Sync**

Run (from repo root):
```bash
uv --directory cloud sync --dev
```
Expected: uv installs fastapi, uvicorn, yfinance (and their deps); no errors.

- [ ] **Step 3: Verify imports resolve**

Run:
```bash
uv --directory cloud run python -c "import fastapi, uvicorn, yfinance, gtts, httpx; print('ok')"
```
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add cloud/pyproject.toml cloud/uv.lock
git commit -m "Add Phase 1 deps: fastapi, uvicorn, yfinance"
```

---

## Task 2: Content engine — defensive `clean()` (TDD)

`clean()` is the most important unit in Phase 1: it makes untrusted Gemma output safe for TTS. Build it first, test-driven, against the exact messy style we saw in Phase 0.

**Files:**
- Create: `cloud/cito/engine.py`
- Test: `cloud/tests/test_engine.py`

- [ ] **Step 1: Write the failing tests**

Create `cloud/tests/test_engine.py`:
```python
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
```

- [ ] **Step 2: Run to verify failure**

Run:
```bash
uv --directory cloud run pytest tests/test_engine.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'cito.engine'`.

- [ ] **Step 3: Implement `clean()`**

Create `cloud/cito/engine.py`:
```python
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
```

- [ ] **Step 4: Run to verify pass**

Run:
```bash
uv --directory cloud run pytest tests/test_engine.py -v
```
Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add cloud/cito/engine.py cloud/tests/test_engine.py
git commit -m "Add content engine clean() with defensive-parsing tests"
```

---

## Task 3: Content engine — template fallback + `generate_script()` (TDD)

**Files:**
- Modify: `cloud/cito/engine.py`
- Modify: `cloud/tests/test_engine.py`

- [ ] **Step 1: Add failing tests**

Append to `cloud/tests/test_engine.py`:
```python
from unittest.mock import patch

from cito.engine import template_fallback, generate_script


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
```

- [ ] **Step 2: Run to verify failure**

Run:
```bash
uv --directory cloud run pytest tests/test_engine.py -v
```
Expected: FAIL — `ImportError: cannot import name 'template_fallback'`.

- [ ] **Step 3: Implement fallback + `generate_script`**

Add to the top imports of `cloud/cito/engine.py`:
```python
import os

import httpx

from cito.constants import GEMINI_ENDPOINT, GEMMA_MODEL
```

Append to `cloud/cito/engine.py`:
```python
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
```

- [ ] **Step 4: Run to verify pass**

Run:
```bash
uv --directory cloud run pytest tests/test_engine.py -v
```
Expected: all tests PASS (11 total).

- [ ] **Step 5: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add cloud/cito/engine.py cloud/tests/test_engine.py
git commit -m "Add template fallback and generate_script to engine"
```

---

## Task 4: Source interface + registry

**Files:**
- Create: `cloud/cito/sources/__init__.py`
- Create: `cloud/cito/sources/base.py`

- [ ] **Step 1: Write the `Source` protocol**

Create `cloud/cito/sources/base.py`:
```python
"""The pluggability contract: every content source is a fetcher + a prompt fragment."""

from typing import Protocol


class Source(Protocol):
    name: str

    def fetch(self) -> dict:
        """Return normalized, meaning-shaped structured data (not raw API shape)."""
        ...

    def prompt_fragment(self, data: dict) -> str:
        """Return a source-specific instruction + the data for the engine prompt."""
        ...
```

- [ ] **Step 2: Write an empty registry (populated in later tasks)**

Create `cloud/cito/sources/__init__.py`:
```python
"""Registry mapping a source key to its instance. Adding a source = one entry here."""

from cito.sources.weather import WeatherSource
from cito.sources.stocks import StockSource

SOURCES = {
    "weather": WeatherSource(),
    "stocks": StockSource(),
}
```

> Note: this import will fail until Tasks 5 and 6 create those classes. That is expected — the next task creates `weather.py`. Do not run the registry import until Task 6 is done.

- [ ] **Step 3: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add cloud/cito/sources/base.py cloud/cito/sources/__init__.py
git commit -m "Add Source protocol and source registry skeleton"
```

---

## Task 5: Weather source (TDD)

**Files:**
- Create: `cloud/cito/sources/weather.py`
- Create: `cloud/tests/test_sources.py`

- [ ] **Step 1: Write the failing test**

Create `cloud/tests/test_sources.py`:
```python
from unittest.mock import patch

from cito.sources.weather import WeatherSource


WTTR_SAMPLE = {
    "current_condition": [
        {"temp_F": "72", "temp_C": "22", "weatherDesc": [{"value": "Sunny"}]}
    ],
    "weather": [
        {"maxtempF": "80", "mintempF": "60", "maxtempC": "27", "mintempC": "16"}
    ],
    "nearest_area": [{"areaName": [{"value": "Austin"}]}],
}


def test_weather_fetch_shape():
    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return WTTR_SAMPLE

    with patch("cito.sources.weather.httpx.get", return_value=FakeResp()):
        data = WeatherSource().fetch()

    assert data["location"] == "Austin"
    assert data["condition"] == "Sunny"
    assert data["high_f"] == 80
    assert data["low_f"] == 60


def test_weather_prompt_fragment_mentions_condition_and_location():
    data = {"location": "Austin", "condition": "Sunny", "high_f": 80, "low_f": 60}
    frag = WeatherSource().prompt_fragment(data)
    assert "Austin" in frag
    assert "Sunny" in frag
    assert "80" in frag
```

- [ ] **Step 2: Run to verify failure**

Run:
```bash
uv --directory cloud run pytest tests/test_sources.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'cito.sources.weather'`.

- [ ] **Step 3: Implement the weather source**

Create `cloud/cito/sources/weather.py`:
```python
"""Weather source — wttr.in (keyless). Dict is shaped around meaning, not wttr.in."""

import httpx

WTTR_URL = "https://wttr.in/?format=j1"


class WeatherSource:
    name = "weather"

    def fetch(self) -> dict:
        resp = httpx.get(WTTR_URL, timeout=15.0, headers={"User-Agent": "curl"})
        resp.raise_for_status()
        raw = resp.json()
        current = raw["current_condition"][0]
        today = raw["weather"][0]
        area = raw["nearest_area"][0]["areaName"][0]["value"]
        return {
            "location": area,
            "condition": current["weatherDesc"][0]["value"],
            "high_f": int(today["maxtempF"]),
            "low_f": int(today["mintempF"]),
        }

    def prompt_fragment(self, data: dict) -> str:
        return (
            f"Weather for {data['location']}: {data['condition']}, "
            f"high {data['high_f']} degrees, low {data['low_f']} degrees. "
            "Give a brief, friendly forecast line."
        )
```

- [ ] **Step 4: Run to verify pass**

Run:
```bash
uv --directory cloud run pytest tests/test_sources.py -v
```
Expected: both weather tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add cloud/cito/sources/weather.py cloud/tests/test_sources.py
git commit -m "Add weather source (wttr.in) with fetch-shape tests"
```

---

## Task 6: Stocks source (TDD)

**Files:**
- Create: `cloud/cito/sources/stocks.py`
- Modify: `cloud/tests/test_sources.py`

> **Stale-data guard — scope note:** the spec calls for a weekend/holiday guard. This
> slice implements the spec's *recommended first version* — an **end-of-day summary**
> framing that anchors on `previous_close` and never says "today", which is exactly what
> "sidesteps the is-the-market-open problem." A date-precise holiday calendar (labeling the
> exact last-trading-day date) is deliberately deferred as a later refinement.

- [ ] **Step 1: Add the failing tests**

Append to `cloud/tests/test_sources.py`:
```python
from unittest.mock import MagicMock

from cito.sources.stocks import StockSource


def test_stocks_fetch_emits_change_and_percent():
    fake_ticker = MagicMock()
    fake_ticker.fast_info = {"last_price": 101.0, "previous_close": 100.0}
    fake_ticker.info = {"shortName": "Apple Inc."}

    with patch("cito.sources.stocks.yf.Ticker", return_value=fake_ticker):
        data = StockSource(tickers=["AAPL"]).fetch()

    quote = data["quotes"][0]
    assert quote["name"] == "Apple Inc."
    assert quote["change_pct"] == 1.0
    assert quote["direction"] == "up"
    assert quote["previous_close"] == 100.0


def test_stocks_prompt_fragment_uses_names_not_tickers():
    data = {"quotes": [
        {"name": "Apple Inc.", "change_pct": 1.2, "direction": "up", "previous_close": 100.0}
    ]}
    frag = StockSource().prompt_fragment(data)
    assert "Apple" in frag
    assert "1.2" in frag
    assert "AAPL" not in frag
```

- [ ] **Step 2: Run to verify failure**

Run:
```bash
uv --directory cloud run pytest tests/test_sources.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'cito.sources.stocks'`.

- [ ] **Step 3: Implement the stocks source**

Create `cloud/cito/sources/stocks.py`:
```python
"""Stock source — yfinance (prototype). Announce the change, not the absolute price.

End-of-day summary framing; isolated behind the fetcher interface so a licensed
provider can replace yfinance later with no downstream change.
"""

import yfinance as yf

DEFAULT_TICKERS = ["AAPL", "MSFT", "GOOGL"]


class StockSource:
    name = "stocks"

    def __init__(self, tickers: list[str] | None = None):
        # Cap the watchlist — listeners tune out past ~5-6 names.
        self.tickers = (tickers or DEFAULT_TICKERS)[:6]

    def fetch(self) -> dict:
        quotes = []
        for symbol in self.tickers:
            ticker = yf.Ticker(symbol)
            info = ticker.fast_info
            last = float(info["last_price"])
            prev = float(info["previous_close"])
            change_pct = round((last - prev) / prev * 100, 1) if prev else 0.0
            quotes.append({
                "name": ticker.info.get("shortName", symbol),
                "previous_close": prev,
                "change_pct": abs(change_pct),
                "direction": "up" if change_pct >= 0 else "down",
            })
        return {"quotes": quotes}

    def prompt_fragment(self, data: dict) -> str:
        lines = [
            f"{q['name']} {q['direction']} about {q['change_pct']} percent"
            for q in data["quotes"]
        ]
        return (
            "End-of-day stock summary (say company names, not tickers; round to "
            "speech-friendly precision; vary verbs like gained/slipped/jumped/fell; "
            "group winners and losers): " + "; ".join(lines) + "."
        )
```

- [ ] **Step 4: Run to verify pass**

Run:
```bash
uv --directory cloud run pytest tests/test_sources.py -v
```
Expected: all 4 source tests PASS.

- [ ] **Step 5: Verify the registry now imports**

Run:
```bash
uv --directory cloud run python -c "from cito.sources import SOURCES; print(sorted(SOURCES))"
```
Expected: `['stocks', 'weather']`

- [ ] **Step 6: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add cloud/cito/sources/stocks.py cloud/tests/test_sources.py
git commit -m "Add stocks source (yfinance) emitting day change + percent"
```

---

## Task 7: TTS module

**Files:**
- Create: `cloud/cito/tts.py`

- [ ] **Step 1: Implement gTTS synthesis behind an interface**

Create `cloud/cito/tts.py`:
```python
"""Text-to-speech behind a tiny interface. gTTS now; ElevenLabs/Polly later drop-ins."""

from pathlib import Path

from gtts import gTTS


def synthesize(text: str, out: Path = Path("announcement.mp3")) -> Path:
    """Render `text` to an audio file and return its path."""
    gTTS(text).save(str(out))
    return out
```

- [ ] **Step 2: Smoke-test it (network required for gTTS)**

Run:
```bash
uv --directory cloud run python -c "from cito.tts import synthesize; print(synthesize('Hello from Cito.'))"
```
Expected: prints `announcement.mp3`; the file exists in `cloud/`.

- [ ] **Step 3: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add cloud/cito/tts.py
git commit -m "Add gTTS text-to-speech module"
```

---

## Task 8: Audio encoder

**Files:**
- Create: `cloud/cito/audio.py`

- [ ] **Step 1: Implement the µ-law encoder**

Create `cloud/cito/audio.py`:
```python
"""Encode an audio file to raw headerless G.711 µ-law (8 kHz mono) via ffmpeg."""

import subprocess
from pathlib import Path


def encode_mulaw(audio_file: Path, out: Path = Path("announcement.ulaw")) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(audio_file),
         "-ar", "8000", "-ac", "1", "-f", "mulaw", str(out)],
        check=True,
        capture_output=True,
    )
    return out
```

- [ ] **Step 2: Smoke-test against the gTTS output**

Run:
```bash
uv --directory cloud run python -c "from pathlib import Path; from cito.tts import synthesize; from cito.audio import encode_mulaw; print(encode_mulaw(synthesize('Hello from Cito.')))"
```
Expected: prints `announcement.ulaw`; the file exists in `cloud/` and is non-empty.

- [ ] **Step 3: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add cloud/cito/audio.py
git commit -m "Add ffmpeg µ-law encoder module"
```

---

## Task 9: Delivery — `MulticastRTPSender`

**Files:**
- Create: `cloud/cito/delivery.py`

- [ ] **Step 1: Implement the sender class (promotes the Phase 0 spike)**

Create `cloud/cito/delivery.py`:
```python
"""Multicast RTP delivery — a clean class promoting the Phase 0 spike.

Reuses cito.rtp.iter_rtp_packets. Sets the macOS outgoing interface + loopback so a
local VLC listener receives the stream.
"""

import random
import socket
import time
from pathlib import Path

from cito.rtp import iter_rtp_packets

PACKET_INTERVAL_S = 0.02
MULTICAST_TTL = 1

# Per-brand defaults — other brands become entries here, not code branches.
BRAND_PORTS = {"yealink": 10000}


def _outgoing_ip() -> str:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    finally:
        probe.close()


class MulticastRTPSender:
    def __init__(self, addr: str = "224.0.1.75", port: int = 10000):
        self.addr = addr
        self.port = port

    def send(self, ulaw_file: Path) -> int:
        with open(ulaw_file, "rb") as f:
            mulaw = f.read()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, MULTICAST_TTL)
        sock.setsockopt(
            socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(_outgoing_ip())
        )
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
        count = 0
        try:
            for packet in iter_rtp_packets(mulaw, ssrc=random.getrandbits(32)):
                sock.sendto(packet, (self.addr, self.port))
                count += 1
                time.sleep(PACKET_INTERVAL_S)
        finally:
            sock.close()
        return count
```

- [ ] **Step 2: Smoke-test (sends to multicast; no VLC needed to confirm no error)**

Run:
```bash
uv --directory cloud run python -c "from pathlib import Path; from cito.delivery import MulticastRTPSender; print(MulticastRTPSender().send(Path('announcement.ulaw')))"
```
Expected: prints a packet count (e.g. a number > 0), no traceback. (Requires `announcement.ulaw` from Task 8.)

- [ ] **Step 3: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add cloud/cito/delivery.py
git commit -m "Add MulticastRTPSender delivery class"
```

---

## Task 10: Pipeline spine (TDD)

**Files:**
- Create: `cloud/cito/pipeline.py`
- Test: `cloud/tests/test_pipeline.py`

- [ ] **Step 1: Write the failing tests**

Create `cloud/tests/test_pipeline.py`:
```python
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
```

- [ ] **Step 2: Run to verify failure**

Run:
```bash
uv --directory cloud run pytest tests/test_pipeline.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'cito.pipeline'`.

- [ ] **Step 3: Implement the pipeline**

Create `cloud/cito/pipeline.py`:
```python
"""The shared spine: both the CLI and the web console call these two functions."""

from dataclasses import dataclass
from pathlib import Path

from cito import audio, tts
from cito.delivery import MulticastRTPSender
from cito.engine import generate_script
from cito.sources import SOURCES


@dataclass
class SendResult:
    packets: int


def generate_announcement(source_keys: list[str]) -> str:
    """Fetch each enabled source, combine fragments, and produce a clean script."""
    fragments = []
    for key in source_keys:
        source = SOURCES[key]
        try:
            data = source.fetch()
            fragments.append(source.prompt_fragment(data))
        except Exception:  # a flaky source must not sink the whole announcement
            continue
    return generate_script(fragments)


def send_announcement(text: str) -> SendResult:
    """Speak `text` verbatim: TTS -> µ-law -> RTP multicast."""
    if not text or not text.strip():
        raise ValueError("cannot send an empty announcement")
    mp3 = tts.synthesize(text.strip())
    ulaw = audio.encode_mulaw(Path(mp3))
    packets = MulticastRTPSender().send(Path(ulaw))
    return SendResult(packets=packets)
```

- [ ] **Step 4: Run to verify pass**

Run:
```bash
uv --directory cloud run pytest tests/test_pipeline.py -v
```
Expected: all 4 pipeline tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add cloud/cito/pipeline.py cloud/tests/test_pipeline.py
git commit -m "Add pipeline spine: generate_announcement + send_announcement"
```

---

## Task 11: CLI runner

**Files:**
- Create: `cloud/cito/run.py`

- [ ] **Step 1: Implement the CLI**

Create `cloud/cito/run.py`:
```python
"""CLI runner — the manual trigger for the pipeline.

Examples:
  uv run python -m cito.run announce --source weather --source stocks
  uv run python -m cito.run announce --message "All-hands at 3pm."
  uv run python -m cito.run announce --source weather --print
"""

import argparse

from cito import pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Fire a Cito announcement.")
    sub = parser.add_subparsers(dest="command", required=True)

    ann = sub.add_parser("announce", help="generate and/or send an announcement")
    ann.add_argument("--source", action="append", default=[], dest="sources",
                     help="source key (repeatable): weather, stocks")
    ann.add_argument("--message", help="send this exact text, skipping generation")
    ann.add_argument("--print", action="store_true", dest="print_only",
                     help="print the script instead of sending")

    args = parser.parse_args()

    if args.message:
        text = args.message
    else:
        if not args.sources:
            parser.error("provide --message or at least one --source")
        text = pipeline.generate_announcement(args.sources)

    print(f"Script: {text}")
    if args.print_only:
        return
    result = pipeline.send_announcement(text)
    print(f"Sent {result.packets} packets.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify the generate-and-print path (no key needed; uses fallback)**

Run:
```bash
uv --directory cloud run python -m cito.run announce --source weather --print
```
Expected: prints `Script: Good morning everyone. Weather for ...` (a real forecast line if `GEMINI_API_KEY` is set, otherwise the template fallback). No send.

- [ ] **Step 3: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add cloud/cito/run.py
git commit -m "Add CLI runner (announce: generate/send/print)"
```

---

## Task 12: Web console (TDD on endpoints)

**Files:**
- Create: `cloud/cito/web/__init__.py`
- Create: `cloud/cito/web/app.py`
- Create: `cloud/cito/web/index.html`
- Test: `cloud/tests/test_web.py`

- [ ] **Step 1: Write the failing endpoint tests**

Create `cloud/tests/test_web.py`:
```python
from unittest.mock import patch

from fastapi.testclient import TestClient

from cito.web.app import app

client = TestClient(app)


def test_index_served():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Cito" in resp.text


def test_generate_endpoint():
    with patch("cito.web.app.pipeline.generate_announcement", return_value="It is sunny."):
        resp = client.post("/generate", json={"sources": ["weather"]})
    assert resp.status_code == 200
    assert resp.json() == {"text": "It is sunny."}


def test_send_endpoint():
    from cito.pipeline import SendResult
    with patch("cito.web.app.pipeline.send_announcement", return_value=SendResult(packets=5)):
        resp = client.post("/send", json={"text": "Hello team."})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "packets": 5}


def test_send_rejects_empty():
    resp = client.post("/send", json={"text": "   "})
    assert resp.status_code == 400
```

- [ ] **Step 2: Run to verify failure**

Run:
```bash
uv --directory cloud run pytest tests/test_web.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'cito.web.app'`.

- [ ] **Step 3: Create the empty package init**

```bash
: > cloud/cito/web/__init__.py
```

- [ ] **Step 4: Implement the FastAPI app**

Create `cloud/cito/web/app.py`:
```python
"""One-page dev console over the headless pipeline."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from cito import pipeline

app = FastAPI(title="Cito Console")
_INDEX = Path(__file__).parent / "index.html"


class GenerateRequest(BaseModel):
    sources: list[str] = []


class SendRequest(BaseModel):
    text: str


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _INDEX.read_text()


@app.post("/generate")
def generate(req: GenerateRequest) -> dict:
    return {"text": pipeline.generate_announcement(req.sources)}


@app.post("/send")
def send(req: SendRequest) -> dict:
    if not req.text or not req.text.strip():
        raise HTTPException(status_code=400, detail="empty announcement")
    result = pipeline.send_announcement(req.text)
    return {"ok": True, "packets": result.packets}
```

- [ ] **Step 5: Create the HTML page**

Create `cloud/cito/web/index.html`:
```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Cito Console</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 640px; margin: 2rem auto; padding: 0 1rem; }
    h1 { font-size: 1.4rem; }
    fieldset { border: 1px solid #ccc; border-radius: 8px; margin-bottom: 1rem; }
    textarea { width: 100%; min-height: 8rem; font-size: 1rem; padding: .5rem; box-sizing: border-box; }
    button { font-size: 1rem; padding: .5rem 1rem; margin-right: .5rem; cursor: pointer; }
    #status { margin-top: 1rem; color: #555; min-height: 1.2rem; }
    label { display: inline-block; margin-right: 1rem; }
  </style>
</head>
<body>
  <h1>Cito — Announcement Console</h1>
  <fieldset>
    <legend>Data pipelines</legend>
    <label><input type="checkbox" id="src-weather" value="weather" /> Weather</label>
    <label><input type="checkbox" id="src-stocks" value="stocks" /> Stocks</label>
  </fieldset>
  <p>Tick sources and <b>Generate</b>, or just type a custom message below, then <b>Send</b>.</p>
  <textarea id="text" placeholder="Announcement text..."></textarea>
  <div style="margin-top:.5rem;">
    <button id="generate">Generate</button>
    <button id="send">Send</button>
  </div>
  <div id="status"></div>

  <script>
    const $ = (id) => document.getElementById(id);
    const status = (msg) => { $("status").textContent = msg; };

    function selectedSources() {
      return ["weather", "stocks"].filter((s) => $("src-" + s).checked);
    }

    $("generate").onclick = async () => {
      const sources = selectedSources();
      if (sources.length === 0) { status("Tick at least one source to generate."); return; }
      status("Generating...");
      try {
        const r = await fetch("/generate", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({ sources }),
        });
        const data = await r.json();
        $("text").value = data.text;
        status("Generated. Edit if you like, then Send.");
      } catch (e) { status("Generate failed: " + e); }
    };

    $("send").onclick = async () => {
      const text = $("text").value.trim();
      if (!text) { status("Nothing to send — type or generate a message first."); return; }
      status("Sending...");
      try {
        const r = await fetch("/send", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({ text }),
        });
        if (!r.ok) { status("Send rejected: " + (await r.text())); return; }
        const data = await r.json();
        status("Sent " + data.packets + " packets to the multicast stream.");
      } catch (e) { status("Send failed: " + e); }
    };
  </script>
</body>
</html>
```

- [ ] **Step 6: Run to verify pass**

Run:
```bash
uv --directory cloud run pytest tests/test_web.py -v
```
Expected: all 4 web tests PASS.

- [ ] **Step 7: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add cloud/cito/web/__init__.py cloud/cito/web/app.py cloud/cito/web/index.html cloud/tests/test_web.py
git commit -m "Add FastAPI dev console (generate/send) with endpoint tests"
```

---

## Task 13: Full suite + README run notes

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Run the whole suite + lint (what CI runs)**

Run:
```bash
uv --directory cloud run ruff check . && uv --directory cloud run pytest -v
```
Expected: ruff clean; all tests pass (RTP + engine + sources + pipeline + web).

- [ ] **Step 2: Add run instructions to the README**

Append to `README.md` (under Status or a new "Running (Phase 1)" section):
```markdown
## Running the Phase 1 console

From `cloud/`:

```bash
# Web console (open http://127.0.0.1:8000)
uv run uvicorn cito.web.app:app --reload

# Or the CLI
uv run python -m cito.run announce --source weather --source stocks
uv run python -m cito.run announce --message "All-hands at 3pm."
```

Listen in VLC: Open Network → RTP, Multicast, address `224.0.1.75`, port `10000`.
Start VLC listening *before* clicking Send.
```

- [ ] **Step 3: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add README.md
git commit -m "Document Phase 1 console + CLI run instructions"
```

---

## Task 14: Manual end-to-end validation (VLC)

No code — confirms the exit criteria by ear. The agent runs the server; the user listens.

- [ ] **Step 1: Start the console**

Run (from repo root, leave running):
```bash
uv --directory cloud run uvicorn cito.web.app:app --reload
```
Open `http://127.0.0.1:8000` in a browser.

- [ ] **Step 2: Start VLC listening**

VLC → Open Network → Open RTP/UDP Stream → Protocol **RTP**, Mode **Multicast**, IP `224.0.1.75`, Port `10000` → Open.

- [ ] **Step 3: Weather announcement**

In the console: tick **Weather**, click **Generate** (text appears), click **Send**.
Expected: a spoken weather line plays in VLC; status shows packet count.

- [ ] **Step 4: Combined weather + stocks**

Tick **Weather** and **Stocks**, **Generate**, **Send**.
Expected: one combined announcement (forecast + market summary) plays.

- [ ] **Step 5: Custom message**

Clear the box, type "This is a custom test announcement.", **Send**.
Expected: the exact typed text plays.

- [ ] **Step 6: Confirm exit criteria**

- ✅ Weather announcement plays via the full pipeline.
- ✅ Stocks works through the same pipeline (added as only a fetcher + fragment).
- ✅ Combined announcement plays as one script.
- ✅ Custom verbatim message plays.
- ✅ Defensive-parsing tests pass (no wrapper/markdown reaches TTS).
- ✅ The console drives the same pipeline the CLI uses.

(No commit — validation only.)
