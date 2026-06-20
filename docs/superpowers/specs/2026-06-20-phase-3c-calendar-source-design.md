# Phase 3c — Calendar Source (as content) (Design)

**Date:** 2026-06-20
**Status:** Approved (building)
**Scope:** The calendar as a pluggable **content source** (spec §3.6) — query today's events
from an iCal/`.ics` feed (with recurrence expansion) and announce them, combining with the
existing sources. The event-driven **trigger** mode is deferred (it needs the Phase 2
scheduler look-ahead loop).

## Goal

Let an admin connect a subscribe-able calendar feed and have Cito read out today's schedule,
on its own or combined with weather/stocks/a document. The calendar is structured data
queried by date — a sibling to weather and stocks, **not** a RAG document.

## Decisions (locked during brainstorming)

| Decision | Choice |
|---|---|
| Connection | iCal/`.ics` feed URL (no OAuth) |
| Recurrence | Full `RRULE` expansion via `icalendar` + `recurring-ical-events` |
| Query window | **Today only** (local date) |
| Feed URL storage | Saved config (`calendar_url`), set via a console field |
| Empty day | A brief "no events scheduled today" line (toggle never a silent no-op) |
| Triggers / OAuth / in-app calendar | **Deferred** |

## Approach

The calendar is another `Source` in the existing registry. It slots into the toggle/combine
flow with zero downstream changes — `fetch()` returns structured event data, `prompt_fragment`
turns it into a speech-ready line, and the engine/pipeline are unchanged.

```
tick Calendar → generate_announcement(["calendar", …])
  → CalendarSource.fetch(): GET .ics → icalendar parse → recurring-ical-events expands
    today's occurrences → {"events": [...]}
  → prompt_fragment → engine (Gemma + <say> + voice) → combined announcement
```

## Components

### `cito/sources/calendar.py` (new)
`CalendarSource` implementing the `Source` protocol (`name`, `fetch() -> dict`,
`prompt_fragment(data) -> str`).

- `name = "calendar"`.
- `fetch() -> dict`:
  - Read `calendar_url` from `config.load_config()`. If empty/missing, raise
    `ValueError("no calendar feed URL configured")` (the pipeline's per-source `try/except`
    skips it, exactly like a flaky source).
  - `httpx.get(url)` the feed (timeout ~15s), `raise_for_status()`.
  - Parse with `icalendar.Calendar.from_ical(resp.text)`.
  - Expand **today's** occurrences with `recurring_ical_events.of(cal).between(start, end)`,
    where `start`/`end` are local midnight today and next midnight.
  - Return `{"events": [{"summary": str, "start": "9:00 AM"|"all day", "all_day": bool}, …]}`
    sorted by start time. Timed events render a spoken-friendly clock time; all-day events
    use `"all day"`.
- `prompt_fragment(data) -> str`: speech-ready data statement, e.g.
  `"Today's schedule: nine AM standup; two PM client call."` When `events` is empty:
  `"There are no events scheduled today."` (No LLM instructions in the fragment — the
  engine's envelope owns the "how"; this also reads cleanly via the template fallback.)

### `cito/config.py` (modify)
- Add `calendar_url` to the persisted config (default `""`). `load_config` returns it;
  `save_config` writes it. (Keep the existing `voice`/`preset` keys.)

### `cito/sources/__init__.py` (modify)
- Register `"calendar": CalendarSource()` in `SOURCES`.

### `cito/web/app.py` (modify)
- `GET /config` also returns `calendar_url`.
- `POST /calendar` body `{url}` → light validation (must start with `http://`/`https://`,
  else 400) → persist via `config.save_config` (preserving voice/preset) → `{ok, calendar_url}`.

### `cito/web/index.html` (modify)
- A **Calendar** checkbox in the Data pipelines fieldset; `selectedSources()` includes
  `calendar`.
- A small **Calendar feed URL** input + **Save URL** button (loads current value from
  `/config`, posts to `/calendar`).

### `cito/run.py`
- No new flag — `--source calendar` works automatically (the source reads the saved URL).

## New dependencies

`icalendar`, `recurring-ical-events`. (`httpx` already present for the feed fetch.)

## Config-save interaction (important)

`save_config` currently persists `{voice, preset}`. To avoid the calendar save clobbering the
voice (and vice-versa), `save_config` must **merge** the incoming fields over the existing
config rather than replace it — or each endpoint loads-merges-saves. The implementation will
load the current config, update only the changed key(s), and save the merged result, so
`/voice` and `/calendar` don't overwrite each other.

## Error handling

- No URL configured → `fetch()` raises → pipeline skips the calendar (announcement still made
  from other toggles).
- Feed fetch/parse failure (network, 404, malformed `.ics`) → skipped with a noted warning;
  a flaky feed never sinks the announcement.
- Empty day → the "no events scheduled today" line (still announceable).
- `POST /calendar` with a non-URL → 400 with a clear message.

## Testing

- `fetch()` with `httpx.get` mocked to return a small `.ics` fixture containing (a) a one-off
  event dated today and (b) a weekly `RRULE` event — with "today" pinned to a date the rule
  lands on (monkeypatch the module's date/`now`). Assert both events appear, sorted by start
  time, with the expected `summary`/`start` shape.
- `fetch()` with no `calendar_url` → raises `ValueError`.
- `prompt_fragment`: non-empty lists the events and their times; empty `events` → the
  "no events scheduled today" line.
- `config`: `calendar_url` round-trips and saving it does not drop `voice`/`preset` (merge).
- web: `POST /calendar` saves a valid URL (and `GET /config` returns it); a non-URL → 400.
- Existing tests stay green (the new source must not change weather/stocks/engine behavior).

## Exit criteria

- With a real iCal feed URL configured, ticking **Calendar** produces an announcement of
  today's events (including a recurring one), played in VLC.
- Calendar combines with Weather/Stocks (and a document) into one announcement; unticking it
  leaves the calendar out.
- An empty day yields the "no events scheduled today" line, not an error.
- A missing/broken feed is skipped gracefully — other toggles still produce an announcement.
- `uv --directory cloud run pytest -q` all green; `ruff check .` clean.

## Deferred (per spec §3.6 / §3.2)

Event-driven triggers (Phase 2 scheduler look-ahead), Google/Microsoft 365 OAuth, the in-app
calendar (event CRUD + storage), multi-day/look-ahead query windows, per-event tagging/filters.
