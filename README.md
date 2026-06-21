# Cito — AI Office Paging System

Cito is a SaaS product that delivers AI-generated announcements (weather, reminders,
calendar events, stock summaries, custom alerts) through existing office IP phone
systems — automatically and on a schedule.

The core design principle: **the only thing a customer configures is how to reach their
phones** (a multicast address, SIP credentials, or a cloud-PBX connection). Everything
upstream — content generation, text-to-speech, scheduling, audio formatting — is
self-contained and identical across every deployment.

## Architecture (at a glance)

A **hybrid cloud + on-prem agent** model:

- **Cloud (Python)** owns the intelligence — dashboard, scheduler, content engine (Gemma
  via REST), TTS, and ffmpeg audio encoding. It ships *finished, encoded audio*.
- **On-prem agent (Go)** owns the "last mile" — it receives encoded audio and delivers it
  to the phones via a pluggable driver (Multicast RTP, SIP paging, or Cloud-PBX API).

The split makes VLAN/firewall problems disappear, isolates phone-brand/PBX differences to
the agent's drivers, and keeps audio-streaming load off the cloud.

## Repository layout

```
docs/     Specification and phased development plan
```

Planned top-level structure (introduced as phases land — see the plan):

```
cloud/    Python: dashboard, scheduler, content engine, TTS, encoder, sources
agent/    Go: thin on-prem delivery agent + drivers
shared/   Wire-format / cloud↔agent contract definitions
```

## Documentation

- [Technical Specification & Architecture](docs/ai-pager-spec.md)
- [Phased Development Plan](docs/ai-pager-development-plan.md)

## Running the Phase 1 console

From `cloud/`:

```bash
# Web console (then open http://127.0.0.1:8000)
uv run uvicorn cito.web.app:app --reload

# Or the CLI
uv run python -m cito.run announce --source weather --source stocks
uv run python -m cito.run announce --message "All-hands at 3pm."
uv run python -m cito.run announce --source weather --print   # generate only, no send
```

Listen in VLC: Open Network → Open RTP/UDP Stream → Protocol **RTP**, Mode
**Multicast**, address `224.0.1.75`, port `10000`. Start VLC listening *before*
clicking Send (RTP multicast is fire-and-forget).

The console now includes a **Voice / personality** editor (presets + live Preview).
Set a voice and Save it; Generate/Send use the saved voice, Preview uses the current
(unsaved) text. The CLI accepts `--voice "…"` to override per run.

Drop in a **document** (.txt / .docx / digital .pdf) to base an announcement on it: in
the console click **Load document** — it appears as a toggle alongside Weather/Stocks and
combines into one announcement. The CLI accepts `--document path/to/file`. Scanned PDFs
and over-long documents are rejected with a clear message.

Connect a **calendar**: paste a subscribe-able iCal/`.ics` feed URL into the Calendar feed
field and Save, then tick **Calendar** — it reads **today's** events (recurring ones included)
and combines into one announcement like any other source. (Event-driven triggers and OAuth
calendars come later.)

Open **Scheduled announcements** (linked from the console) to save announcements that fire
automatically: pick **Sources** (generated fresh each time) or a **fixed message**, set a
time + days, and Save. **Run now** fires any of them immediately for testing. Note: the
scheduler runs inside the console process, so run uvicorn **without `--reload`** for
scheduling, and jobs fire only while the server is up.

## Status

Phase 0 and Phase 1 complete. Phase 3a complete: layered prompt with `<say>` extraction
so Gemma returns clean announcements (not just the fallback), plus an admin voice/personality
layer (presets, validation, live preview) across the engine, CLI, and console. Phase 3b
complete: document input pipeline (.txt/.docx/.pdf → whole-doc injection) as a toggleable
input that combines with the sources. Phase 3c complete: calendar content source (iCal feed
→ today's events with recurrence) as another combinable toggle. Phase 2a complete: an
APScheduler-backed scheduler with saved announcements (source-based or fixed-message) on a
time + day-of-week schedule, managed from a console page with Run-now.
