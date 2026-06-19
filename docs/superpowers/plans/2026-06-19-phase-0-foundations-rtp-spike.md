# Phase 0 — Foundations & RTP Spike Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the minimal Cito monorepo scaffolding and prove that synthesized RTP plays cleanly in VLC, plus confirm a Gemma REST round-trip.

**Architecture:** A `uv`-managed Python project under `cloud/`. RTP header construction is a pure, importable function (`cito/rtp.py`) unit-tested offline; a thin sender script (`cito/spikes/rtp_send.py`) wraps it with a UDP multicast socket and 20 ms pacing. A separate fixture script generates a spoken µ-law test file (gTTS → ffmpeg). A standalone script confirms Gemma over direct REST. `agent/` and `shared/` are placeholder dirs for later phases.

**Tech Stack:** Python 3.11+ (via `uv`), `httpx`, `python-dotenv`, `gTTS`, `pytest`, `ruff`, ffmpeg (CLI), VLC (manual validation), GitHub Actions.

---

## File Structure

```
cloud/
  pyproject.toml                  # uv project: deps, dev deps, pytest + ruff config
  .env.example                    # GEMINI_API_KEY= (blank)
  cito/
    __init__.py
    constants.py                  # GEMINI_ENDPOINT + GEMMA_MODEL (single source of truth)
    rtp.py                        # pure RTP packetization (importable, tested)
    spikes/
      __init__.py
      rtp_send.py                 # CLI: stream a µ-law file as RTP multicast
      make_test_audio.py          # CLI: spoken sentence -> test.wav + test.ulaw
      gemma_check.py              # CLI: one REST call to Gemma, print sentence
  tests/
    test_rtp_packet.py            # offline asserts: header bytes, seq +1, ts +160
agent/README.md                   # placeholder (Go agent: Phase 2)
shared/README.md                  # placeholder (cloud<->agent wire format: later)
.github/workflows/ci.yml          # ruff + pytest on push
```

All commands below are run from the `cloud/` directory unless noted.

---

## Task 1: Tooling & project scaffold

**Files:**
- Create: `cloud/pyproject.toml`
- Create: `cloud/cito/__init__.py`, `cloud/cito/spikes/__init__.py`
- Create: `cloud/.env.example`
- Create: `agent/README.md`, `shared/README.md`

- [ ] **Step 1: Install uv and ffmpeg (Homebrew)**

Run (from anywhere):
```bash
brew install uv ffmpeg
```
Expected: both install. Verify:
```bash
uv --version && ffmpeg -version | head -1
```
Expected: a uv version string and an ffmpeg version line.

- [ ] **Step 2: Create the package directories**

Run (from repo root `/Users/dwightbritton/Desktop/Cito`):
```bash
mkdir -p cloud/cito/spikes cloud/tests agent shared .github/workflows
```

- [ ] **Step 3: Write `cloud/pyproject.toml`**

```toml
[project]
name = "cito-cloud"
version = "0.0.0"
description = "Cito cloud — AI office paging system"
requires-python = ">=3.11"
dependencies = [
    "httpx",
    "python-dotenv",
    "gTTS",
]

[dependency-groups]
dev = [
    "pytest",
    "ruff",
]

[tool.uv]
package = false

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
```

- [ ] **Step 4: Write the package init files (empty)**

Create `cloud/cito/__init__.py` and `cloud/cito/spikes/__init__.py`, both empty.

```bash
: > cloud/cito/__init__.py
: > cloud/cito/spikes/__init__.py
```

- [ ] **Step 5: Write `cloud/.env.example`**

```
# Copy to cloud/.env (gitignored) and fill in. Phase 0 needs only this key.
GEMINI_API_KEY=
```

- [ ] **Step 6: Write placeholder READMEs**

`agent/README.md`:
```markdown
# agent/

Placeholder for the Go on-prem delivery agent (Phase 2). No code yet.
```

`shared/README.md`:
```markdown
# shared/

Placeholder for the cloud↔agent wire-format contract (Phase 2). No code yet.
```

- [ ] **Step 7: Sync the environment**

Run (from `cloud/`):
```bash
cd cloud && uv sync --dev
```
Expected: uv resolves and installs httpx, python-dotenv, gTTS, pytest, ruff into `.venv`; prints a summary. A `uv.lock` appears.

- [ ] **Step 8: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add cloud/pyproject.toml cloud/uv.lock cloud/.env.example \
        cloud/cito/__init__.py cloud/cito/spikes/__init__.py \
        agent/README.md shared/README.md
git commit -m "Scaffold cloud uv project and placeholder dirs (Phase 0)"
```

---

## Task 2: RTP packetization (pure, TDD)

This is the de-risk core: the exact bytes that make a phone play audio. Tested offline, no sockets.

**Files:**
- Create: `cloud/cito/rtp.py`
- Test: `cloud/tests/test_rtp_packet.py`

- [ ] **Step 1: Write the failing tests**

Create `cloud/tests/test_rtp_packet.py`:
```python
import struct

from cito.rtp import build_rtp_header, iter_rtp_packets, RTP_PAYLOAD_SIZE


def test_header_first_byte_is_0x80():
    # Version 2, no padding/extension/CSRC -> 0x80
    assert build_rtp_header(seq=0, timestamp=0, ssrc=0x11223344)[0] == 0x80


def test_header_payload_type_is_pcmu():
    # Marker 0, payload type 0 (PCMU/G.711 µ-law) -> 0x00
    assert build_rtp_header(seq=0, timestamp=0, ssrc=0)[1] == 0x00


def test_header_is_12_bytes():
    assert len(build_rtp_header(seq=1, timestamp=160, ssrc=0)) == 12


def test_sequence_increments_by_one():
    data = b"\xff" * (RTP_PAYLOAD_SIZE * 3)
    packets = list(iter_rtp_packets(data, ssrc=0x11223344))
    seqs = [struct.unpack("!H", p[2:4])[0] for p in packets]
    assert seqs == [0, 1, 2]


def test_timestamp_increments_by_160():
    data = b"\xff" * (RTP_PAYLOAD_SIZE * 3)
    packets = list(iter_rtp_packets(data, ssrc=0))
    timestamps = [struct.unpack("!I", p[4:8])[0] for p in packets]
    assert timestamps == [0, 160, 320]


def test_full_packet_is_172_bytes():
    data = b"\xff" * RTP_PAYLOAD_SIZE
    packets = list(iter_rtp_packets(data, ssrc=0))
    assert len(packets[0]) == 172


def test_short_final_payload_is_preserved():
    data = b"\xff" * (RTP_PAYLOAD_SIZE + 80)
    packets = list(iter_rtp_packets(data, ssrc=0))
    assert len(packets) == 2
    assert len(packets[1]) == 12 + 80
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `cloud/`):
```bash
uv run pytest tests/test_rtp_packet.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'cito.rtp'` (or import error).

- [ ] **Step 3: Write the implementation**

Create `cloud/cito/rtp.py`:
```python
"""Pure RTP packetization for G.711 µ-law (PCMU) audio.

No sockets, no timing — just bytes, so it can be unit-tested offline.
160 bytes of µ-law = 20 ms of audio at 8 kHz.
"""

import struct

RTP_HEADER_SIZE = 12
RTP_PAYLOAD_SIZE = 160          # bytes of µ-law per packet (20 ms @ 8 kHz)
PAYLOAD_TYPE_PCMU = 0           # G.711 µ-law
TIMESTAMP_INCREMENT = 160       # samples per packet


def build_rtp_header(seq: int, timestamp: int, ssrc: int) -> bytes:
    """Build a 12-byte RTP header (V=2, P=0, X=0, CC=0, M=0, PT=0/PCMU)."""
    return struct.pack(
        "!BBHII",
        0x80,                       # V=2, P=0, X=0, CC=0
        PAYLOAD_TYPE_PCMU,          # M=0, PT=0 (PCMU)
        seq & 0xFFFF,
        timestamp & 0xFFFFFFFF,
        ssrc & 0xFFFFFFFF,
    )


def iter_rtp_packets(mulaw: bytes, ssrc: int, start_seq: int = 0, start_ts: int = 0):
    """Yield 172-byte RTP packets (12-byte header + up to 160-byte payload).

    The final packet may carry a shorter payload if the audio length is not a
    multiple of 160 bytes.
    """
    seq = start_seq
    timestamp = start_ts
    for offset in range(0, len(mulaw), RTP_PAYLOAD_SIZE):
        payload = mulaw[offset:offset + RTP_PAYLOAD_SIZE]
        yield build_rtp_header(seq, timestamp, ssrc) + payload
        seq = (seq + 1) & 0xFFFF
        timestamp = (timestamp + TIMESTAMP_INCREMENT) & 0xFFFFFFFF
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (from `cloud/`):
```bash
uv run pytest tests/test_rtp_packet.py -v
```
Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add cloud/cito/rtp.py cloud/tests/test_rtp_packet.py
git commit -m "Add RTP packetization with offline header tests"
```

---

## Task 3: RTP sender CLI

Wraps `iter_rtp_packets` with a UDP multicast socket and 20 ms pacing.

**Files:**
- Create: `cloud/cito/spikes/rtp_send.py`

- [ ] **Step 1: Write the sender**

Create `cloud/cito/spikes/rtp_send.py`:
```python
"""Stream a raw µ-law file as RTP multicast (the Phase 0 spike).

Usage:  uv run python -m cito.spikes.rtp_send test.ulaw
"""

import argparse
import random
import socket
import time

from cito.rtp import iter_rtp_packets

DEFAULT_ADDR = "224.0.1.75"
DEFAULT_PORT = 10000
PACKET_INTERVAL_S = 0.02          # 20 ms cadence
MULTICAST_TTL = 1


def send(path: str, addr: str = DEFAULT_ADDR, port: int = DEFAULT_PORT) -> int:
    with open(path, "rb") as f:
        mulaw = f.read()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, MULTICAST_TTL)

    ssrc = random.getrandbits(32)
    count = 0
    try:
        for packet in iter_rtp_packets(mulaw, ssrc=ssrc):
            sock.sendto(packet, (addr, port))
            count += 1
            time.sleep(PACKET_INTERVAL_S)
    finally:
        sock.close()
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Stream a µ-law file as RTP multicast.")
    parser.add_argument("file", help="raw headerless µ-law file (e.g. test.ulaw)")
    parser.add_argument("--addr", default=DEFAULT_ADDR)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    count = send(args.file, args.addr, args.port)
    print(f"Sent {count} packets to {args.addr}:{args.port}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-test against a dummy file (no VLC yet)**

Run (from `cloud/`):
```bash
head -c 1600 /dev/zero > /tmp/silence.ulaw
uv run python -m cito.spikes.rtp_send /tmp/silence.ulaw
```
Expected: `Sent 10 packets to 224.0.1.75:10000` (1600 bytes / 160 = 10 packets), no traceback. Takes ~0.2 s.

- [ ] **Step 3: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add cloud/cito/spikes/rtp_send.py
git commit -m "Add RTP multicast sender CLI"
```

---

## Task 4: Spoken test-audio generator

**Files:**
- Create: `cloud/cito/spikes/make_test_audio.py`

- [ ] **Step 1: Write the generator**

Create `cloud/cito/spikes/make_test_audio.py`:
```python
"""Generate the spoken test audio for the RTP spike.

Produces test.wav (double-click to verify quality) and test.ulaw (raw headerless
G.711 µ-law, 8 kHz mono) — the artifact rtp_send.py streams.

Usage:  uv run python -m cito.spikes.make_test_audio
"""

import subprocess
from pathlib import Path

from gtts import gTTS

TEST_SENTENCE = "This is a test of the Cito paging system."


def main() -> None:
    mp3 = Path("test.mp3")
    wav = Path("test.wav")
    ulaw = Path("test.ulaw")

    gTTS(TEST_SENTENCE).save(str(mp3))

    # Normal WAV for double-click listening.
    subprocess.run(["ffmpeg", "-y", "-i", str(mp3), str(wav)], check=True)

    # Raw headerless G.711 µ-law, 8 kHz mono — what a phone expects.
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(mp3),
         "-ar", "8000", "-ac", "1", "-f", "mulaw", str(ulaw)],
        check=True,
    )

    size = ulaw.stat().st_size
    print(f"Wrote {wav} and {ulaw} ({size} bytes ~= {size / 8000:.1f}s of audio)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it (requires network for gTTS)**

Run (from `cloud/`):
```bash
uv run python -m cito.spikes.make_test_audio
```
Expected: ffmpeg output, then `Wrote test.wav and test.ulaw (NNNN bytes ~= N.Ns of audio)`. Files `test.wav`, `test.ulaw`, `test.mp3` exist in `cloud/`.

- [ ] **Step 3: Confirm the WAV sounds right**

Double-click `cloud/test.wav` (or `open test.wav`) — you should hear "This is a test of the Cito paging system." This verifies audio quality before streaming.

- [ ] **Step 4: Commit**

(The generated `test.*` files are gitignored by the root `.gitignore` — only the script is committed.)
```bash
cd /Users/dwightbritton/Desktop/Cito
git add cloud/cito/spikes/make_test_audio.py
git commit -m "Add spoken test-audio generator (gTTS + ffmpeg)"
```

---

## Task 5: VLC validation (the core proof — manual)

No code. This is the make-or-break exit criterion: hear our own RTP stream in VLC.

- [ ] **Step 1: Start VLC listening FIRST**

Open VLC → Media → Open Network Stream → enter:
```
rtp://@224.0.1.75:10000
```
Click Play. VLC sits silent, waiting. (It must join the group before any packets are sent — RTP multicast is fire-and-forget.)

- [ ] **Step 2: Run the sender**

Run (from `cloud/`):
```bash
uv run python -m cito.spikes.rtp_send test.ulaw
```
Expected: terminal prints `Sent NNN packets ...`, and within ~1 second you **hear** "This is a test of the Cito paging system." play through VLC.

- [ ] **Step 3: Judge the result**

- Clean, intelligible speech → ✅ exit criterion met; the core premise holds.
- Static/buzzing instead of speech → likely a codec mismatch; note it (A-law fallback is a Phase 1 config flag).
- Nothing plays → VLC may not have joined before sending, or macOS multicast loopback is off. Retry with VLC started first; if still silent, set `IP_MULTICAST_LOOP` on the socket and re-run.

(No commit — this task produces no files.)

---

## Task 6: Gemma round-trip (Check A)

**Files:**
- Create: `cloud/cito/constants.py`
- Create: `cloud/cito/spikes/gemma_check.py`

- [ ] **Step 1: Write the constants module**

Create `cloud/cito/constants.py`:
```python
"""Single source of truth for the model integration.

Swapping models/providers must be a one-line edit here — the model id and
endpoint appear nowhere else.
"""

GEMMA_MODEL = "gemma-4-26b-a4b-it"
GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
```

- [ ] **Step 2: Write the round-trip script**

Create `cloud/cito/spikes/gemma_check.py`:
```python
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
```

- [ ] **Step 3: Create your local .env with the key**

Run (from `cloud/`), replacing the placeholder with your real key:
```bash
cp .env.example .env
# then edit cloud/.env so the line reads: GEMINI_API_KEY=your-real-key
```
(`cloud/.env` is gitignored — never committed.)

- [ ] **Step 4: Run the check**

Run (from `cloud/`):
```bash
uv run python -m cito.spikes.gemma_check
```
Expected: `HTTP 200` then `Gemma says: <a real one-sentence announcement>`.
If you get HTTP 400/404, the model id or endpoint is wrong — fix it in `cito/constants.py` only.

- [ ] **Step 5: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add cloud/cito/constants.py cloud/cito/spikes/gemma_check.py
git commit -m "Add Gemma REST round-trip check and model constants"
```

---

## Task 7: CI stub

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Write the workflow**

Create `.github/workflows/ci.yml`:
```yaml
name: CI

on:
  push:
  pull_request:

jobs:
  lint-test:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: cloud
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          python-version: "3.11"
      - run: uv sync --dev
      - run: uv run ruff check .
      - run: uv run pytest -v
```

- [ ] **Step 2: Verify lint + tests pass locally (what CI will run)**

Run (from `cloud/`):
```bash
uv run ruff check . && uv run pytest -v
```
Expected: ruff reports no errors; all RTP tests PASS.

- [ ] **Step 3: Commit and push**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add .github/workflows/ci.yml
git commit -m "Add CI stub: ruff + pytest on push"
git push
```
Expected: push succeeds; the Actions tab on GitHub shows the workflow running green.

---

## Phase 0 Exit Criteria (verify all)

- [ ] A µ-law file plays through VLC via our own RTP stream — clean, intelligible (Task 5).
- [ ] `uv run pytest -v` passes: header correct, seq +1, timestamp +160 (Task 2).
- [ ] `gemma_check.py` prints HTTP 200 and a generated sentence (Task 6).
- [ ] `uv` and `ffmpeg` run from the project shell; CI stub runs ruff + pytest green (Tasks 1, 7).
