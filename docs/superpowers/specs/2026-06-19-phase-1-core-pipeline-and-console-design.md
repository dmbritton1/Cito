# Phase 1 — Core Pipeline + Dev Console (Design)

**Date:** 2026-06-19
**Status:** Approved (pending written-spec review)
**Scope:** A vertical slice of Phase 1 — an end-to-end content pipeline (real data →
Gemma → speech → µ-law → RTP) driven by a headless CLI engine, with a thin web console
on top for testing (toggle sources, generate/edit text, send).

## Goal

Prove the pluggable source design end to end: real data → AI script (cleaned) → speech →
phone-format audio → RTP stream playable in VLC, with two sources (weather + stocks)
sharing one engine and one downstream pipeline. Make it pleasant to test via a one-page
web console.

## Decisions (locked during brainstorming)

| Decision | Choice |
|---|---|
| Test driver | Headless CLI engine + thin FastAPI web console on top |
| Content sources | Weather (wttr.in, keyless) + Stocks (yfinance, EOD) + Custom verbatim text |
| Generate/edit flow | One editable text box = source of truth; toggled sources combine into one announcement via Gemma; Custom = type your own and Send without generating |
| Personality / voice control | **Deferred to Phase 3** (this slice uses only the hidden envelope + source-data layers; no AI tone steering) |
| Send target | VLC multicast `224.0.1.75:10000` (same as the Phase 0 spike) |
| TTS | gTTS (behind an interface; swappable later) |
| Real-Yealink hardware test | **Deferred** (no phone in the dev loop yet) |

## Non-goals (deferred on purpose)

Real phone hardware, SIP/cloud-PBX, scheduling/APScheduler, auth, persistence/DB,
the full prompt-editing UI (presets, validation, live preview, per-type overrides),
the Go agent, multi-site. These belong to Phases 2–4.

## Architecture

The load-bearing idea: **all logic lives in a headless pipeline that both the CLI and the
web console call.** The web page is a thin shell over two operations:

- `generate_announcement(sources) -> str` — fetch each enabled source, combine their
  structured data, run Gemma with defensive cleaning, return announceable text.
- `send_announcement(text) -> SendResult` — TTS → ffmpeg µ-law encode → RTP multicast.

```
[console / CLI] --sources--> generate_announcement --> editable text
[console / CLI] --text-----> send_announcement     --> gTTS -> µ-law -> RTP -> VLC
```

Custom messages skip `generate_announcement` entirely: the text the user typed goes
straight to `send_announcement`.

## Components (new files under `cloud/cito/`)

### `sources/base.py` — the pluggability contract
A `Source` protocol/ABC. Each source provides:
- `name: str`
- `fetch() -> dict` — normalized, meaning-shaped structured data (NOT raw API shape)
- `prompt_fragment(data: dict) -> str` — source-specific instruction + the data, with
  speech-formatting rules (spoken-friendly numbers, no markdown) living here.

A registry maps a source key (`"weather"`, `"stocks"`) to its instance so the runner and
web layer can resolve toggles to sources. Adding a source = a new file + a registry entry,
nothing downstream.

### `sources/weather.py`
- Fetches `https://wttr.in/?format=j1` via httpx (keyless).
- Returns a dict shaped around meaning: `{location, condition, high_c/high_f, low_c/low_f}`
  (not wttr.in's raw structure), so OpenWeatherMap can drop in later behind the same dict.
- `prompt_fragment` asks Gemma for a brief, friendly forecast line.

### `sources/stocks.py`
- Uses `yfinance` for an admin-configured watchlist (default a few tickers, capped ~5–6).
- Pulls current/last price **and** previous close; emits the day's change and percent —
  the *change* is the signal, not the absolute price.
- Defaults to an **end-of-day summary** framing (data is final/unambiguous).
- Weekend/holiday **stale-data guard**: if the latest close isn't today's trading day,
  label it as the last close's date rather than implying "today."
- `prompt_fragment` bakes in: round to speech-friendly precision ("up about 1.2 percent"),
  say company names not tickers, vary verbs, group winners vs losers.

### `engine.py` — content engine
- `generate_script(prompt_fragments: list[str]) -> str`:
  - Assembles a layered prompt: a fixed **envelope** ("You write a short spoken office
    announcement. Return ONLY the announcement text — no preamble, no markdown, no lists,
    no options, 1–3 sentences.") + the concatenated **source-data fragments**. (The
    editable voice layer is intentionally absent in this slice.)
  - POSTs to Gemma (`GEMMA_MODEL` via `GEMINI_ENDPOINT` from `constants.py`).
  - Runs `clean()` on the result.
- `clean(raw: str) -> str` — **defensive parsing (mandatory):** strip leading/trailing
  whitespace; remove wrapping quotes/backticks/code fences; strip a leading
  "Here's your announcement:"-style preamble; strip markdown bullet/asterisk lines; if the
  result is empty or absurdly long, raise/flag so the caller can fall back.
- **Template fallback:** when `GEMINI_API_KEY` is absent (or Gemma fails/`clean` rejects),
  build a deterministic announceable string directly from the source dicts. Keeps the
  product runnable and testable offline.

### `tts.py`
- `synthesize(text: str) -> Path` — gTTS → mp3/wav, behind a simple interface so
  ElevenLabs/Polly/Google TTS are later drop-ins.

### `audio.py`
- `encode_mulaw(audio_file: Path) -> Path` — ffmpeg `-ar 8000 -ac 1 -f mulaw` to a raw
  headerless `.ulaw`. Generalized from the Phase 0 `make_test_audio` ffmpeg step.

### `delivery.py`
- `MulticastRTPSender` class promoting the Phase 0 `rtp_send` to a clean lifecycle:
  construct with `addr`/`port` (and the macOS `IP_MULTICAST_IF`/`LOOP` setup), `send(file)`,
  graceful socket close. Reuses `cito.rtp.iter_rtp_packets`.
- A small per-brand port table stub (Yealink default) so other brands are later entries.

### `pipeline.py` — the shared spine
- `generate_announcement(source_keys: list[str]) -> str` — resolve keys → fetch each →
  collect `prompt_fragment`s → `engine.generate_script(...)`.
- `send_announcement(text: str) -> SendResult` — `tts.synthesize` → `audio.encode_mulaw`
  → `MulticastRTPSender.send`. Returns packet count / status.

### `run.py` — CLI
- `announce --source weather --source stocks` → generate + send.
- `--message "..."` → send verbatim text, skipping generation.
- `--no-send` / `--print` → generate and print the script without sending (for inspection).

### `web/app.py` + `web/index.html` — the console
- FastAPI app:
  - `GET /` → serves `index.html`.
  - `POST /generate` body `{"sources": ["weather","stocks"]}` → `{"text": "..."}`.
  - `POST /send` body `{"text": "..."}` → `{"ok": true, "packets": N}`.
- One HTML page (vanilla JS `fetch`, no framework): checkboxes for Weather and Stocks, a
  large editable `<textarea>`, a **Generate** button (fills the textarea), a **Send**
  button (speaks the textarea's exact contents), and a status line. Custom message = clear
  the box, type, Send.
- Launched via `uv run uvicorn cito.web.app:app --reload` (documented in README).

## New dependencies

`fastapi`, `uvicorn`, `yfinance`. (`httpx` already present, used for Gemma and wttr.in.)

## Data flow (combined-source announcement)

1. User ticks Weather + Stocks, clicks **Generate**.
2. `POST /generate` → `generate_announcement(["weather","stocks"])`.
3. Each source `fetch()`es its dict; each yields a `prompt_fragment`.
4. `engine.generate_script` assembles envelope + both fragments, calls Gemma, `clean()`s.
   (No key / failure → template fallback string.)
5. Cleaned text returns to the page, fills the textarea.
6. User edits if desired, clicks **Send**.
7. `POST /send` → `send_announcement(text)` → gTTS → µ-law → RTP to `224.0.1.75:10000`.
8. User hears it in VLC (listening on `rtp://@224.0.1.75:10000`).

## Error handling

- Source fetch failure → that source is skipped with a noted warning; if all sources fail,
  the engine falls back / returns a clear error to the console status line.
- Gemma non-200 or `clean()` rejection → template fallback (never send raw/garbage to TTS).
- Empty textarea on Send → rejected with a clear message, no audio produced.
- ffmpeg/gTTS failure → surfaced to the status line; nothing is streamed.

## Testing

- `clean()` against deliberately messy strings: wrapping quotes, backticks/code fences,
  a chatty preamble, markdown asterisks/bullets, and the exact multi-option dump style we
  saw from Gemma in Phase 0 → assert the result is a clean announceable string.
- Template fallback returns an announceable string from sample dicts with no key.
- `weather.fetch()` returns the documented dict shape (httpx mocked).
- `stocks.fetch()` returns change + percent + previous close and respects the weekend
  guard (yfinance mocked).
- `engine.generate_script` with mocked Gemma returns cleaned text; falls back on failure.
- `pipeline.generate_announcement` / `send_announcement` with mocked TTS/encode/delivery.
- Web endpoints via FastAPI `TestClient`: `/generate` and `/send` happy paths + empty-text
  rejection.
- Existing RTP packet tests stay green.

## Exit criteria

- A generated weather announcement plays out of VLC via the full pipeline.
- A stock end-of-day summary works through the same pipeline, added only as a new fetcher +
  prompt fragment (nothing downstream changed) — the pluggability proof.
- A combined weather+stocks announcement generates as one script and plays.
- A custom typed message sends verbatim and plays.
- Defensive-parsing tests pass (no wrapper text / markdown can reach TTS).
- The web console can toggle sources, Generate (edit), and Send, all driving the same
  headless pipeline the CLI uses.
