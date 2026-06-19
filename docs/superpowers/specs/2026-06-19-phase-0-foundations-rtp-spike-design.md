# Phase 0 — Foundations & RTP Spike (Design)

**Date:** 2026-06-19
**Status:** Approved (pending written-spec review)
**Scope:** Cito Phase 0 only — foundations + the RTP de-risk spike. Phases 1–4 are out of scope.

## Goal

De-risk the single most uncertain technical claim — that we can craft RTP packets a
phone (or VLC stand-in) will actually play — and stand up the minimal scaffolding
everything else builds on.

Phase 0 contains **two independent checks**, deliberately not connected (the full
Gemma → speech → VLC pipeline is Phase 1):

- **Check A — Gemma round-trip:** a Python script prints a real generated sentence.
- **Check B — RTP spike:** a generated µ-law file plays cleanly through VLC via our own
  RTP multicast stream.

## Non-goals

- No Go agent (placeholder dir only; Go lands in Phase 2).
- No content sources, TTS abstraction, scheduler, or dashboard (Phase 1+).
- No real phone hardware (VLC is the stand-in; Yealink test is Phase 1).
- No Wireshark requirement (optional, deferred — VLC satisfies the exit criterion).
- Gemma's output is **not** wired into the spoken test audio (that's Phase 1).

## Decisions (locked during brainstorming)

| Decision | Choice |
|---|---|
| Scope | Phase 0 only |
| Python tooling | `uv` (manages Python 3.11+; ignores system 3.9.6) |
| Gemma key | User has a `GEMINI_API_KEY`; goes in gitignored `.env` |
| Sequencing | Minimal scaffold, then spike fast |
| Test audio | Spoken sentence (gTTS → ffmpeg → µ-law), fixed text |
| Gemma↔audio | Kept separate (no connection in Phase 0) |
| Wireshark | Deferred / optional |

## Repository structure

```
cloud/                     # Python (uv project root)
  pyproject.toml
  cito/
    __init__.py
    constants.py           # GEMINI endpoint URL + GEMMA_MODEL = "gemma-4-26b-a4b-it"
  spikes/
    rtp_send.py            # RTP packetizer/sender (the core de-risk)
    make_test_audio.py     # generates the µ-law (+ wav) test file via gTTS + ffmpeg
    gemma_check.py         # one-call REST round-trip → prints generated text
  tests/
    test_rtp_packet.py     # asserts header bytes, seq +1, ts +160 (no network)
agent/README.md            # placeholder — Go agent in Phase 2
shared/README.md           # placeholder — cloud↔agent wire format later
.env.example               # GEMINI_API_KEY= (blank); real .env is gitignored
.github/workflows/ci.yml   # ruff + pytest on push (CI stub)
```

`agent/` and `shared/` exist now as placeholders so the monorepo contract has a home;
they contain no code in Phase 0.

## Tooling & dependencies

- Install via Homebrew: `uv`, `ffmpeg`.
- `uv` pins Python 3.11+.
- Python deps (Phase 0): `httpx`, `python-dotenv`, `gTTS`, `pytest`, `ruff`.

## Components

### `cito/constants.py`
Single source of truth for the model integration:
- `GEMINI_ENDPOINT` — the REST endpoint URL.
- `GEMMA_MODEL = "gemma-4-26b-a4b-it"`.

Swapping models/providers later must be a one-line edit here. No model string or
endpoint appears anywhere else.

### `spikes/gemma_check.py` (Check A)
- Loads `GEMINI_API_KEY` from `.env` via `python-dotenv`.
- One `httpx` POST to `GEMINI_ENDPOINT` with `GEMMA_MODEL` and a trivial prompt.
- Asserts HTTP 200; prints the generated sentence.
- Fails loudly with a clear message if the key/endpoint/model is wrong.

### `spikes/make_test_audio.py` (test fixture for Check B)
- Speaks a fixed sentence (e.g. *"This is a test of the Cito paging system."*) with gTTS → MP3.
- Shells out to ffmpeg to produce two artifacts:
  - `test.wav` — normal, double-clickable, to verify audio quality before streaming.
  - `test.ulaw` — raw headerless G.711 µ-law, 8 kHz mono (`-ar 8000 -ac 1 -f mulaw`).
- Sanity-checks the µ-law byte count against duration (~8,000 bytes/sec).

### `spikes/rtp_send.py` (Check B — the heart of Phase 0)
- Opens a raw µ-law file; walks it in 160-byte slices (20 ms each).
- Per slice builds a 12-byte RTP header:
  - byte 0 = `0x80` (version 2, no padding/extension/CSRC)
  - byte 1 = `0x00` (payload type 0 = PCMU)
  - bytes 2–3 = 16-bit sequence number, +1 per packet
  - bytes 4–7 = 32-bit timestamp, +160 per packet
  - bytes 8–11 = fixed random 32-bit SSRC
- Concatenates header + 160-byte payload = 172-byte packet.
- Sends to multicast `224.0.1.75:10000` over UDP on a 20 ms `time.sleep` cadence.
- Sets `IP_MULTICAST_TTL`. Clean lifecycle: stop at end of file, close socket cleanly.
- Address/port are constants/CLI args, not hardcoded deep in logic.

### `tests/test_rtp_packet.py`
Offline unit tests (no network/hardware):
- Header byte 0 == `0x80`, byte 1 == `0x00`.
- Sequence number increments by exactly 1 across packets.
- Timestamp increments by exactly 160 across packets.
- Payload slices are 160 bytes (last packet may be short — assert handling is defined).

### `.github/workflows/ci.yml`
Minimal stub: on push, set up `uv`, install deps, run `ruff` then `pytest`.

## Testing / developer workflow (what the user does)

**Check A — Gemma:**
```
uv run python -m cito.spikes.gemma_check
```
Terminal prints `200 OK` and a generated sentence. Done.

**Check B — RTP in VLC:**
1. `uv run python -m cito.spikes.make_test_audio` → produces `test.wav` + `test.ulaw`.
   (Optionally double-click `test.wav` to confirm audio quality.)
2. Open VLC → Media → Open Network Stream → `rtp://@224.0.1.75:10000` → Play. VLC waits.
3. `uv run python -m cito.spikes.rtp_send test.ulaw` → the spoken sentence plays in VLC.

VLC **must** be listening before the sender runs — RTP multicast is fire-and-forget.

## Exit criteria

- ✅ A µ-law file plays through VLC via our own RTP stream (clean, intelligible).
- ✅ `test_rtp_packet.py` passes (header correct, seq +1, timestamp +160).
- ✅ Gemma returns a generated sentence from `gemma_check.py` (HTTP 200).
- ✅ `ffmpeg -version` and `uv` both run from the project shell; CI stub runs ruff + pytest.

## Risks & mitigations

- *RTP cadence jittery in Python* → acceptable on LAN/loopback for speech; revisit pacing
  only if VLC audio is audibly choppy.
- *Multicast loopback blocked on macOS* → test VLC on the same machine first; if the
  socket needs it, enable `IP_MULTICAST_LOOP`. Real-network multicast is a Phase 1 concern.
- *Gemma endpoint/region surprises* → isolated to `constants.py`; a change is one edit.
- *Codec mismatch (static not speech)* → µ-law is the NA default; A-law is a one-flag
  ffmpeg change if needed (formalized as config in Phase 1).
