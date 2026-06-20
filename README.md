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

## Status

Phase 0 and Phase 1 complete. Phase 3a complete: layered prompt with `<say>` extraction
so Gemma returns clean announcements (not just the fallback), plus an admin voice/personality
layer (presets, validation, live preview) across the engine, CLI, and console.
