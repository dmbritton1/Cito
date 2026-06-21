# Phase 2a — Scheduler + Announcement Management (Design)

**Date:** 2026-06-20
**Status:** Approved (building)
**Scope:** The first Phase 2 sub-project — saved announcement records, a cron-style
scheduler that fires them automatically, and a console menu to create/list/edit/delete/run
them. Pure Python on the existing stack; fires through the existing pipeline to VLC. The Go
agent, SIP driver, and broader dashboard are separate later sub-projects.

## Goal

Let an admin save announcements and have them fire automatically on a schedule (e.g. an
8:30 AM weekday weather + calendar briefing), plus a "Run now" button to test on demand.
This is the productized version of the manual CLI/console trigger, and the keystone that
later unblocks the calendar's event-driven triggers.

## Decisions (locked during brainstorming)

| Decision | Choice |
|---|---|
| Schedule model | Time (HH:MM) + day-of-week selection, local timezone |
| Content types | Source-based (generated fresh at fire time) OR fixed verbatim message |
| Persistence | Lightweight JSON store (`announcements.json`, gitignored) — no DB |
| Scheduler lifecycle | APScheduler `BackgroundScheduler` inside the console process |
| Management UI | A dedicated Announcements page (keeps the main console uncluttered) |
| Run now | Included (fire a saved announcement immediately) |

## Architecture

Two new cloud modules + a management page, reusing the existing pipeline:

```
announcements.json  ──load at startup──►  Scheduler (APScheduler BackgroundScheduler)
   ▲  CRUD via console                        │  cron fires at the saved time/days
   │                                           ▼
Announcements page ──"Run now"───────►  run_announcement(record)
                                          ├ kind=sources  → pipeline.generate_announcement(sources) → send_announcement
                                          └ kind=message  → pipeline.send_announcement(message)
```

## Components

### `cito/announcements.py` (new) — persisted records + CRUD
- Record shape:
  ```python
  {
    "id": "<uuid4>",
    "name": "Morning briefing",
    "kind": "sources" | "message",
    "sources": ["weather", "calendar"],   # used when kind == "sources"
    "message": "Reminder: standup in five minutes.",  # used when kind == "message"
    "time": "08:30",                        # 24h local HH:MM
    "days": ["mon", "tue", "wed", "thu", "fri"],  # subset of mon..sun
  }
  ```
- `STORE_PATH = cloud/announcements.json` (gitignored). Functions:
  - `list_announcements() -> list[dict]` (empty list if file missing).
  - `create(data) -> dict` (assigns `id`, validates, appends, saves).
  - `update(id, data) -> dict` (validates, replaces, saves; raises if not found).
  - `delete(id) -> None`.
  - `get(id) -> dict` (raises if not found).
- `AnnouncementError(ValueError)` for validation failures (admin-facing message).
- `validate(data)`: `name` non-empty; `kind` in {sources, message}; if sources → at least one
  valid source key (weather/stocks/calendar); if message → non-empty text; `time` matches
  `HH:MM` (00-23:00-59); `days` a non-empty subset of the 7 day codes.

### `cito/scheduler.py` (new) — APScheduler wrapper
- A module-level `BackgroundScheduler` (local timezone).
- `start()` — start the scheduler and register a job per saved announcement (idempotent;
  safe to call once on app startup).
- `_trigger(record) -> CronTrigger` — `CronTrigger(day_of_week=",".join(days), hour, minute,
  timezone=<local>)` parsed from `time`/`days`.
- `reschedule(record)` — add or replace the job with id `record["id"]`.
- `unschedule(id)` — remove the job if present.
- `run_announcement(record)` — the fire path: `kind == "sources"` →
  `text = pipeline.generate_announcement(record["sources"])`; `kind == "message"` →
  `text = record["message"]`; then `pipeline.send_announcement(text)`. (Voice is applied
  inside `generate_announcement` via saved config.) Each job calls `run_announcement`.

### `cito/web/app.py` (modify)
- On startup (`@app.on_event("startup")` or lifespan), call `scheduler.start()`.
- Endpoints (Pydantic models for the body):
  - `GET /announcements` → `list_announcements()`.
  - `POST /announcements` → create → `scheduler.reschedule(rec)` → return rec; `AnnouncementError` → 400.
  - `PUT /announcements/{id}` → update → `scheduler.reschedule(rec)` → return rec; not found → 404, bad → 400.
  - `DELETE /announcements/{id}` → delete → `scheduler.unschedule(id)` → `{ok: true}`.
  - `POST /announcements/{id}/run` → `run_announcement(get(id))` → `{ok, text}` (404 if missing).
  - `GET /announcements-ui` → serve `announcements.html`.

### `cito/web/announcements.html` (new) — management page
- A table/list of saved announcements (name; "8:30 AM · Mon–Fri"; type) with **Edit**,
  **Delete**, **Run now** per row.
- A create/edit form: name; type selector (Sources → Weather/Stocks/Calendar checkboxes |
  Message → textarea); a time input; day-of-week checkboxes.
- Vanilla JS calling the endpoints; a status line. The main console (`/`) gets a link to
  this page.

### New dependency
`APScheduler`.

## Scheduler lifecycle (known limitation)

The scheduler runs in the uvicorn process, so jobs fire **only while the console server is
running** — correct for laptop testing and the natural seam for Phase 4's always-on hosting.
Uvicorn must run **without `--reload`** for scheduling (reload spawns a second process that
would double-fire). The README run note will say so.

## Data flow (a scheduled briefing)

1. Admin creates "Morning briefing" — kind=sources [weather, calendar], 08:30, Mon–Fri.
2. `POST /announcements` saves it and `scheduler.reschedule` registers a cron job.
3. At 08:30 on a weekday the job calls `run_announcement` → `generate_announcement(["weather",
   "calendar"])` (Gemma + saved voice) → `send_announcement` → TTS → µ-law → RTP → phones/VLC.
4. "Run now" invokes the same `run_announcement` immediately for testing.

## Error handling

- Invalid create/update (bad time, no days, empty content) → `AnnouncementError` → 400.
- Unknown id on update/delete/run → 404.
- A source failing at fire time is already handled inside the pipeline (skipped); a fully
  failed generation falls back to the template. A job that raises is caught/logged by the
  scheduler so one bad fire doesn't kill the scheduler.
- Empty resulting text → `send_announcement` raises ValueError (caught, surfaced/logged).

## Testing

- `announcements.py`: create/list/update/delete round-trip on a temp JSON path; id is unique;
  `validate` rejects bad time (`"25:00"`), empty days, unknown source, empty message, bad kind.
- `scheduler.py`: `_trigger` maps `time`/`days` to the right `CronTrigger` fields;
  `run_announcement` calls `generate_announcement` for kind=sources and uses the verbatim
  message for kind=message, then `send_announcement` (pipeline mocked); `reschedule`/
  `unschedule` add/remove a job on a scheduler instance (assert via `get_job`).
- web: CRUD endpoints with the store mocked return the right shapes; `POST /…/run` with the
  pipeline mocked returns `{ok, text}`; bad body → 400; unknown id → 404.
- Existing tests stay green.

## Exit criteria

- A saved source-based announcement (e.g. weather, 1 minute from now, today's weekday) fires
  automatically and plays in VLC while the console runs.
- A fixed-message announcement fires verbatim on its schedule.
- "Run now" fires any saved announcement immediately.
- Create/edit/delete from the Announcements page persist across a server restart (JSON store)
  and re-register on startup.
- `uv --directory cloud run pytest -q` all green; `ruff check .` clean.

## Deferred

Calendar **event-driven** triggers (the scheduler's look-ahead loop — next sub-project now
that the scheduler exists), real DB/auth/multi-user, quiet hours/priority/approval (Phase 4),
24/7 hosting, the Go agent + SIP (separate Phase 2 sub-projects).
