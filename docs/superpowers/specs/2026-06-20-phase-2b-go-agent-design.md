# Phase 2b — Go On-Prem Agent + Multicast Driver (Design)

**Date:** 2026-06-20
**Status:** Approved (building)
**Scope:** The first half of the on-prem split — define the cloud↔agent contract, build a
Go agent that connects to the cloud over WSS and delivers finished audio via a multicast
driver, and hook the cloud's send path to push to a connected agent (falling back to the
existing in-process Python multicast when no agent is connected). SIP, installers, and the
agent's local queue are later cycles.

## Goal

Move the "last mile" of delivery out of the Python cloud and into a small, installable Go
agent — proving the architecture that lets Cito reach phones behind an office firewall. The
cloud ships finished µ-law audio; the agent does the RTP multicast. End-to-end still
terminates at VLC on the laptop, just delivered via the agent.

## Decisions (locked during brainstorming)

| Decision | Choice |
|---|---|
| Delivery integration | Agent if connected; otherwise the existing in-process Python multicast (fallback) |
| Audio transport | Base64-embedded in the WSS message (files are tens of KB; no fetch URL) |
| Transport | WSS only (REST fallback deferred) |
| Auth | A single shared token validated on the WS handshake |
| Heartbeat | Minimal — the live socket = "online" (WS ping/pong); rich metrics deferred |
| Observability | Both sides **log which delivery path** was taken (agent vs fallback) so the test is visible |
| Agent language | Go (new `agent/` module); Python cloud untouched except the WS endpoint + fallback hook |

## Architecture

```
CLOUD (Python/FastAPI)                              OFFICE / laptop
──────────────────────                              ───────────────
scheduler/console → generate → TTS → encode µ-law
   → send_announcement:
       agent connected? ──yes──► WSS push {audio_b64, addr, port} ─► GO AGENT
                         ──no───► Python MulticastRTPSender (today)        │ multicast RTP
                                                                           ▼
                                                                      phones / VLC
```

## The cloud↔agent contract (`shared/`)

A JSON message the cloud pushes over the open WSS connection:
```json
{ "type": "announce", "codec": "pcmu", "addr": "224.0.1.75", "port": 10000,
  "audio_b64": "<base64 of the raw µ-law bytes>" }
```
- The agent connects to `wss://<cloud>/agent?token=<shared-token>`; a bad/missing token is
  rejected (close code 1008).
- The contract is documented in `shared/agent-protocol.md` as the single source both sides
  reference.

## Components

### Cloud (Python)

**`cito/agent_link.py`** (new) — tracks the connected agent and delivers to it.
- Holds the current agent `WebSocket` (single agent for this slice) and the asyncio loop.
- `register(ws, loop)` / `unregister()` called by the WS endpoint on connect/disconnect.
- `deliver(ulaw_path, addr, port) -> bool` — callable from sync code (scheduler thread,
  request handlers). Reads + base64-encodes the µ-law, builds the message, and sends it to
  the agent socket via `asyncio.run_coroutine_threadsafe(ws.send_json(msg), loop)` (the
  sync→async bridge). Returns `True` if an agent was connected and the send succeeded,
  `False` otherwise. Logs `delivered via agent` or (when none) leaves the caller to fall back.

**`cito/web/app.py`** (modify)
- `WS /agent` endpoint: validate `token` query param against the configured token (close 1008
  if bad); `agent_link.register(ws, loop)`; keep the socket open (receive loop for ping/pong
  and disconnect detection); `agent_link.unregister()` in a finally.
- The shared token comes from env (`CITO_AGENT_TOKEN`, defaulting to a dev value via
  `.env`/`.env.example`).

**`cito/pipeline.py`** (modify) — `send_announcement`:
- After `encode_mulaw`, call `agent_link.deliver(ulaw, addr, port)`. If it returns `True`,
  log `delivered via agent` and return a `SendResult` (packets reported by the agent path as
  the slice count, or 0/—). If `False`, log `no agent — local fallback` and use the existing
  `MulticastRTPSender` as today. The empty-text guard stays.

### Go agent (`agent/`)

New Go module (`go.mod`, module path `cito/agent`). Files:
- **`main.go`** — load config from env/flags (`CITO_CLOUD_WS` URL, `CITO_AGENT_TOKEN`);
  connect to the cloud WSS with a reconnect loop (log `connected to cloud` / reconnect
  attempts); read messages; dispatch `announce` to the active driver; log
  `received announce → sent N packets`.
- **`rtp.go`** — RTP packetization: 12-byte header (`0x80`, PT `0x00`/PCMU, seq +1,
  timestamp +160, fixed SSRC) + 160-byte payloads → 172-byte packets (a Go port of
  `cito/rtp.py`).
- **`multicast.go`** — the multicast `Driver`: opens a UDP socket, sets the outgoing
  interface (the macOS `IP_MULTICAST_IF` equivalent) + multicast loopback, and sends packets
  on a **drift-corrected 20 ms cadence** (absolute deadlines, the fix we validated in Python).
- **`driver.go`** — a `Driver` interface (`Deliver(mulaw []byte, addr string, port int) error`)
  so the SIP driver (2c) is a second implementation.
- **`rtp_test.go`** — Go unit tests for the packetizer (header bytes, seq +1, ts +160,
  172-byte full packet, short final payload).

### Auth & config

A shared token (`CITO_AGENT_TOKEN`) in the cloud env and the agent config; the cloud rejects
WS connections without it. Added to `.env.example`. Per-site revocable tokens are deferred.

### Prerequisite & deps

`brew install go` (Go not yet installed). Go dep: `github.com/gorilla/websocket`. Python side
uses FastAPI's built-in WebSocket support (no new Python dep).

## Data flow (with an agent connected)

1. Go agent starts → connects to `wss://localhost:8000/agent?token=…` → cloud logs
   `agent connected`, agent logs `connected to cloud`.
2. Announcement fires (Run-now/scheduled) → cloud generates → TTS → µ-law.
3. `send_announcement` → `agent_link.deliver` base64s the audio, pushes the `announce`
   message → cloud logs `delivered via agent`.
4. Agent decodes → multicast driver streams RTP (drift-corrected) → logs
   `received announce → sent N packets` → VLC plays it.
5. With the agent stopped, step 3 returns `False` → cloud logs `local fallback` → Python
   `MulticastRTPSender` plays it. (Proves both paths.)

## Error handling

- Bad/missing token → WS close 1008; agent logs the rejection and retries with backoff.
- Agent disconnects mid-run → `agent_link.deliver` returns `False` (or the send raises and is
  caught) → cloud falls back to local for that announcement.
- Cloud unreachable at agent start → agent retries with backoff (no crash).
- Malformed message at the agent → logged and skipped (doesn't kill the agent).
- Empty announcement text → `send_announcement` still rejects (unchanged).

## Testing

- **Go (`go test ./...`)**: `rtp_test.go` asserts header `0x80`/PT `0x00`, seq +1,
  timestamp +160, 172-byte full packet, and a short final payload — mirroring the Python
  packet tests.
- **Cloud (pytest)**: `WS /agent` accepts a valid token and rejects a bad one (FastAPI
  `TestClient` websocket); `agent_link.deliver` returns `False` with no agent registered;
  `send_announcement` uses the local fallback when no agent is connected (existing behavior
  preserved; `agent_link`/delivery mocked). Existing 107 tests stay green.
- **End-to-end (manual, by ear)**: run cloud + `go run ./agent` + VLC; fire an announcement
  and confirm the **agent terminal** shows `sent N packets` and VLC plays it; then **stop the
  agent**, fire again, and confirm the cloud logs `local fallback` and VLC still plays.

## Exit criteria

- `go test ./...` and `uv --directory cloud run pytest -q` both green; `ruff check .` clean.
- With the Go agent connected, a fired announcement is delivered **via the agent** (agent
  logs packet count) and plays in VLC.
- With no agent connected, the cloud falls back to local multicast and still plays (existing
  flow intact).
- The cloud logs make the chosen path (`via agent` vs `local fallback`) visible.
- A bad token is rejected at the WS handshake.

## Deferred (later cycles)

SIP driver (2c — a second `Driver` impl), REST fallback transport, the agent's local
queue/replay across cloud outages, rich heartbeat metrics + a dashboard health view, native
installers (`.msi`/`.deb`) + code-signing, multi-agent/multi-site, per-site revocable tokens,
the CI build matrix for Go targets.
