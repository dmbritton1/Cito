# AI Office Paging System — Phased Development Plan

A build-oriented companion to the technical spec (`ai-pager-spec.md`). Where the spec describes *what the system is*, this document describes *how to build it*, broken into sequenced phases with concrete tasks, deliverables, and exit criteria.

**Guiding sequencing principle:** prove the riskiest, most novel thing first (getting AI-generated audio out of a real desk phone), then expand outward — first to the architecture that makes it a product (the agent + delivery drivers), then to the features that make it valuable (sources, documents, prompt control), then to the polish that makes it sellable (hardening, security, scale). Each phase ends in something demonstrable.

**How to read each phase:** Objective → Workstreams (grouped tasks, each bullet expanded with the *what*, the *how*, and the *why/gotcha*) → Key deliverables → Exit criteria (the bar to move on) → Risks & mitigations.

---

## Phase 0 — Foundations & Spike (1–2 weeks)

**Objective:** De-risk the single most uncertain technical claim — that you can craft RTP packets that a phone (or a stand-in) will actually play — before committing to architecture. Also stand up the minimal scaffolding everything else builds on.

### Workstreams

**0.1 Project scaffolding**
- **Repo layout — one repo, two top-level dirs.** Create `cloud/` (Python) and `agent/` (Go) even though the agent isn't built until Phase 2. A monorepo keeps the cloud↔agent contract (shared message shapes, version constants) in one place and lets you version them together; splitting later is cheap, merging later is not. Add a top-level `README`, `docs/` (drop the spec and this plan in here), and a `shared/` folder for the wire-format definitions both sides will eventually reference.
- **Python environment.** Use `uv` (fast, lockfile-based) or a plain `venv` + `pip-tools`. Pin Python to a single version (3.11+). Wire up `ruff` for lint+format and `pytest` from day one — the defensive-parsing tests in Phase 1 depend on the test harness already existing. Add a `Makefile` or `justfile` with `make test`, `make run`, `make lint` so commands are discoverable.
- **Secrets convention.** A `.env` file loaded via `python-dotenv`, with `.env` in `.gitignore` and a committed `.env.example` listing every key name with blank values. Start with `GEMINI_API_KEY`; the file will grow to hold weather/stock/TTS provider keys. Never read secrets from anywhere but environment variables in code — this makes the eventual move to a hosting platform's secret store a no-op.
- **CI stub.** A minimal GitHub Actions workflow that runs lint + tests on push. It does nothing useful yet, but having the pipeline exist means Phase 2's build matrix is an extension rather than a from-scratch effort.

**0.2 The RTP spike (the critical de-risk)**
- **Write the packetizer.** A throwaway script that opens a raw µ-law file (headerless, one byte per sample) and walks it in 160-byte slices. For each slice, build a 12-byte RTP header: version/flags byte `0x80`, payload-type byte `0x00` (PCMU), a 16-bit sequence number that increments per packet, a 32-bit timestamp that increases by 160 per packet, and a fixed random 32-bit SSRC. Concatenate header + 160-byte payload = 172-byte packet.
- **Send on a 20 ms cadence.** Loop with `time.sleep(0.02)` between `sock.sendto()` calls to a multicast group (e.g. `224.0.1.75:10000`). Set the socket's `IP_MULTICAST_TTL`. Acknowledge up front that `time.sleep` isn't perfectly precise — that's fine for speech on a LAN; only revisit if audio is audibly choppy.
- **Validate in VLC.** Open VLC → Media → Open Network Stream → `rtp://@224.0.1.75:10000`, then run the sender. Hearing clean audio through VLC proves the packetization and stream are correct *without needing any phone*. This is the single highest-value test in the whole project — it collapses the biggest unknown.
- **Inspect in Wireshark.** Capture on the loopback/local interface, filter to the multicast address, and confirm: sequence numbers increment by 1, timestamps step by exactly 160, payload type reads as ITU-T G.711 PCMU. Wireshark can even decode and replay the RTP stream as audio — a second independent confirmation.
- **Why this is make-or-break:** every later phase assumes you can synthesize a phone-playable stream. If VLC plays your stream cleanly, the core premise holds and everything downstream is "just" engineering. If it doesn't, you want to know in week one.

**0.3 Account & access checklist**
- **Gemma reachability.** Make one trivial `httpx` POST to the Gemini endpoint with the Gemma model id and confirm a 200 with generated text. This flushes out auth/endpoint/region issues before you build anything on top. Record the exact endpoint URL and model string in a constants file.
- **ffmpeg on PATH.** Confirm `ffmpeg -version` runs from the same shell your code runs in. This is the dependency people forget; catching it now avoids a confusing failure mid-pipeline. Note the install method per-OS in the README (`brew`, `apt`, Windows static build).
- **TTS — defer the paid one.** Use gTTS (no key) for the spike and Phase 1. Note in the README that ElevenLabs/Google Cloud TTS is a later swap behind the TTS interface, so no account is needed yet.

### Key deliverables
- A repo with `cloud/` + `agent/` structure, lint/test tooling, and a CI stub that runs on push.
- A working multicast RTP sender spike, validated both by ear (VLC) and by packet inspection (Wireshark).
- A confirmed one-call Gemma REST round-trip returning text.

### Exit criteria
- ✅ A µ-law file plays through VLC via your own RTP stream.
- ✅ Wireshark confirms well-formed RTP headers (seq +1, timestamp +160, PT 0).
- ✅ Gemma returns a generated sentence from a Python script.

### Risks & mitigations
- *RTP cadence is jittery in Python* → acceptable on LAN for speech; note it and revisit pacing (e.g. a tighter timing loop) only if audio is choppy.
- *Multicast blocked locally* → test loopback first (VLC on the same machine); defer real-network multicast to Phase 1 once a phone is in the loop.
- *Gemma endpoint/region surprises* → resolve in 0.3 before writing the content engine; isolate the URL + model string in one constants file so a change is one edit.

---

## Phase 1 — Prove the Core (3–5 weeks)

**Objective:** End-to-end proof: real data → AI script → speech → phone-format audio → out of an actual Yealink speaker. Plus prove the pluggable-source design by adding a *second* source with zero downstream changes. Everything here can be Python; the production agent (Go) comes in Phase 2.

### Workstreams

**1.1 Content engine (Gemma via REST)**
- **The core module.** Implement `generate_script(structured_data, prompt_template) → str`. It formats the data into the prompt, POSTs to Gemma (`gemma-4-26b-a4b-it`) via `httpx`, and returns cleaned text. Keep it synchronous and simple for now; async only if the runner needs it.
- **One model-id constant.** Put the model string and endpoint URL in a single constants module. The spec's "pluggable provider" promise lives or dies on this — when you later swap to a licensed model or a different provider, it must be a one-line edit, not a search-and-replace.
- **Defensive parsing — treat output as untrusted.** Implement a `clean()` step: strip leading/trailing whitespace, remove wrapping quotes/backticks/code fences, strip a leading "Here's your announcement:"-style preamble, and reject empty or suspiciously long output (fall back if so). Write `pytest` cases feeding deliberately messy strings (markdown asterisks, surrounding quotes, a chatty preamble) and assert the cleaned result is announceable. This is the bug that's invisible until it's broadcasting out of every speaker — lock it down with tests now.
- **Template fallback.** A deterministic, non-LLM path that builds a serviceable string from the structured data (e.g. f-string with the temp and condition). Selected automatically when no `GEMINI_API_KEY` is present. This keeps the whole product runnable and testable offline, and is a genuine product feature (an AI-free tier).

**1.2 Source: Weather (first fetcher)**
- **Define the source interface.** Settle the contract every source implements: `fetch() → dict` returning normalized structured data, paired with a prompt template. Document the dict shape. Getting this interface right is the whole point of Phase 1 — stocks (1.3) will stress-test it.
- **Weather fetcher (keyless first).** Use `wttr.in` (no API key) so you can move fast. Crucially, shape the returned dict around *meaning* (location, today's high/low, condition, notable change) not around `wttr.in`'s raw response — so OpenWeatherMap can drop in later by populating the same dict without touching the prompt or engine.
- **Weather prompt template.** A short instruction that, given the dict, asks Gemma for a brief, friendly forecast line. Keep the speech-formatting rules (spoken-friendly numbers, no markdown) here in the source layer, distinct from the data — this previews the prompt-layering work in Phase 3.

**1.3 Source: Stocks (proves pluggability)**
- **Second fetcher, same interface.** Implement a stocks fetcher using `yfinance`, returning a dict in the same shape contract as weather. The test of the architecture: if this requires changing the engine, the TTS step, or the delivery step, the abstraction leaked — fix it before moving on.
- **Announce the change, not the absolute.** Pull current price *and* previous close so you can compute/emit the day's change and percent. "Apple up 1.2%" is the signal; "Apple at $228" is noise. Most `yfinance` quote objects expose both in one call — make sure the dict carries the delta, not just the spot price.
- **End-of-day-summary framing.** Default the stock source to a post-close summary where the data is final and unambiguous, sidestepping the "is the market even open" problem. Add a simple weekend/holiday guard so a Tuesday-after-a-holiday run doesn't read Friday's close as "today."
- **Stock-specific prompt rules.** Bake into the prompt: round to speech-friendly precision ("up about 1.2 percent," never "1.234"), say company names not tickers ("Apple," not "A-A-P-L," or TTS spells letters), and vary the verbs (gained/slipped/jumped/fell) while grouping winners vs losers.
- **Validation goal (write it down).** The explicit success condition for this workstream is "adding stocks touched only a new fetcher + a new prompt." If it touched anything downstream, note what leaked and refactor the interface — this is cheaper now than after three more sources exist.

**1.4 TTS + encoding pipeline**
- **TTS module behind an interface.** `synthesize(text) → audio_file`. Implement with gTTS first, but define the interface so ElevenLabs/Google Cloud TTS/Polly are later drop-ins. Output a known high-quality format (e.g. MP3/WAV) — don't let TTS-provider quirks leak past this boundary.
- **ffmpeg encode to phone format.** Shell out to ffmpeg to downsample to 8 kHz, mix to mono, and encode G.711 µ-law into a raw headerless file (`-ar 8000 -ac 1 -f mulaw`). Verify the byte count matches expectation (8,000 bytes/sec). This is the artifact the RTP sender consumes.
- **Codec as config.** Make µ-law vs A-law a configuration value defaulting to µ-law (North America). This is a one-flag ffmpeg difference, and exposing it now means the eventual European/region support is a config change, not a code change. Optionally note G.722 wideband as a future quality option.

**1.5 Delivery: Multicast RTP (productionize the spike)**
- **Promote the spike to a real module.** Refactor the Phase 0 throwaway into a `MulticastRTPSender` with clean lifecycle: construct with address/port/codec, `send(audio_file)`, and a graceful stop. Handle the end-of-stream cleanly (stop sending, don't leave a half-open socket).
- **Per-brand config stub.** Add a small lookup keyed by phone brand that supplies defaults (Yealink's typical multicast port to start). You only need Yealink working now, but structuring the lookup means Poly/Cisco/Grandstream/Snom/Fanvil are later table entries, not code branches. Document where the per-brand values come from.

**1.6 Orchestration**
- **The runner.** A single entry point that wires the pipeline end to end: pick a source → `fetch()` → `generate_script()` → `synthesize()` → `encode()` → `send()`. Keep it linear and readable; this is the spine everything else hangs off.
- **Manual trigger first.** Drive it from a CLI command (`run announce --source weather`) so you can fire announcements on demand during development. A real scheduler is Phase 2/3; if convenient, drop in a stub `APScheduler` job here to prove timed firing, but don't over-invest — the dashboard owns scheduling later.

**1.7 Real-hardware test**
- **Coordinate with IT early.** The long pole is network access, not code. Ask IT to enable multicast paging on **one** Yealink phone on an unused channel/priority, and confirm whether your dev machine can even reach the voice VLAN (it often can't — see risks). Do this conversation in week one of the phase, not the last week.
- **Stream to that one phone.** Point the sender at the configured multicast address and fire a generated weather announcement. Start with one phone specifically so a bug can't blast the whole office.
- **Confirm the real-world qualities.** Check intelligibility, volume level (phone paging volume can differ from call volume), and end-to-end latency. Note any static (could indicate A-law vs µ-law mismatch) and any clipping. Capture findings — they inform whether codec defaults or volume normalization need attention.

### Key deliverables
- A runnable Python pipeline producing a spoken weather (and stock) announcement on demand.
- Working multicast delivery to a real Yealink phone.
- Two content sources sharing one engine and one downstream pipeline, proving the pluggable pattern.

### Exit criteria
- ✅ A generated weather announcement plays out of a real Yealink speaker.
- ✅ A stock end-of-day summary works through the same pipeline with only a new fetcher + prompt added.
- ✅ Defensive-parsing unit tests pass (no wrapper text can reach TTS).
- ✅ Audio is intelligible at phone quality.

### Risks & mitigations
- *VLAN isolation blocks the dev machine from the phone* → coordinate with IT in week one; if blocked, run the sender from a machine that sits on the voice VLAN, or have IT bridge multicast for the test channel.
- *gTTS sounds robotic* → acceptable for proof; ElevenLabs is a later swap behind the TTS interface (1.4).
- *yfinance flakiness/ToS* → it's prototype scaffolding only; the licensed-provider swap is already designed for and lands in Phase 3.
- *Codec mismatch → static* → if you hear static not speech, try A-law; the config flag from 1.4 makes this a one-line test.

---

## Phase 2 — Productize: Agent, Drivers, Dashboard (6–10 weeks)

**Objective:** Turn the working pipeline into a deployable product. Split cloud from on-prem, build the Go agent with multiple delivery drivers (adding the all-important SIP path), package it cleanly, and give admins a basic web UI.

### Workstreams

**2.1 Cloud ↔ agent split**
- **Define the contract first.** Before code, specify the cloud→agent message: encoded audio (or a short-lived URL to fetch it) plus delivery metadata (which driver, target multicast address or paging extension, codec, priority). Put this schema in the `shared/` folder so both the Python cloud and Go agent reference one source of truth. The discipline here is that the cloud ships *finished audio* — the agent never runs AI/TTS/encoding.
- **Persistent connection + REST fallback.** Implement a WebSocket (WSS) channel for the cloud to push announcements to the agent in real time, with a REST endpoint as fallback for environments where long-lived sockets are awkward. The socket also carries heartbeats (2.2).
- **Agent auth.** Each agent registers to the cloud with a scoped, revocable credential (per-site token). Design it so a leaked token affects only one site and can be rotated from the dashboard. No shared global secret.

**2.2 The Go agent (production)**
- **Rebuild delivery in Go.** Port the delivery layer to Go specifically for its clean cross-compilation and standalone static binary — the properties that make the single-binary installer (2.4) possible. Keep the agent deliberately small: receive audio, run a driver, report status.
- **Driver interface.** Define `Driver.Deliver(audio, metadata) error`, with the active driver chosen by config. This mirrors the cloud's source-pluggability on the delivery side — multicast, SIP, and later cloud-PBX are all implementations of one interface.
- **Multicast driver.** Port the Phase 1 Python RTP logic to Go (same 12-byte header, 160-byte payload, 20 ms cadence, per-brand port table). Go's tighter timing control may actually improve pacing over Python's `sleep`.
- **Heartbeat.** Emit a periodic heartbeat over the WSS channel so the dashboard can show online/healthy and flag a site that's gone dark. Include enough in the heartbeat (agent version, active driver, last-delivery status) to be useful for support.
- **Local cache/queue.** Persist scheduled/pending announcements locally so a brief cloud outage doesn't drop a page — the agent can replay from its queue when connectivity returns. Bound the queue and define a staleness policy (don't fire a weather announcement that's now hours old).

**2.3 SIP paging driver (biggest enterprise unlock)**
- **Register as a SIP extension.** Implement a driver that uses a PJSIP-class library (or a mature Go SIP stack, possibly via cgo) to register the agent on the customer's PBX exactly like any phone — using credentials the IT admin provisions. From the PBX's view, the agent is just another extension.
- **Dial the paging group + stream audio.** On trigger, the driver "calls" the existing paging-group extension and streams the announcement's RTP into that call. The PBX then fans audio to every phone — so this path works with any SIP PBX regardless of phone brand and entirely sidesteps VLAN concerns (the PBX already reaches every phone).
- **Local test before any real PBX.** Stand up Asterisk in Docker, register a softphone (Linphone/MicroSIP/Zoiper) as an extension, create a paging group, and have the agent call into it. You hear the announcement through the softphone, and the full SIP flow (REGISTER → INVITE → 200 OK → RTP) exercises exactly as it would on real hardware. Only after this works locally do you point it at a customer PBX.

**2.4 Packaging & CI**
- **Native single-binary installer (the default).** Wrap the Go binary in OS-native installers — `.msi` (Windows), `.deb`/`.rpm` (Linux) — targeting Windows + Linux x86-64 first (where voice-network hosts usually live). Each installer registers the agent as an auto-starting background service: Windows Service Control Manager, Linux `systemd` unit. The goal is a double-click, click-Next, enter-connection-details experience for a non-Docker shop.
- **Docker image (for technical customers).** Publish a container image too — technical IT teams that already run Docker will prefer it and it deploys onto any VLAN in minutes. One image, no per-OS work, so it's nearly free to maintain alongside the installers.
- **CI matrix + signing placeholders.** Extend the Phase 0 CI stub into a release matrix (GitHub Actions) that builds every OS/arch target from one pipeline (Go makes this `GOOS`/`GOARCH`). Wire in code-signing *steps* now but with placeholder/no-op certs — the real Authenticode and Apple certs are acquired at launch (Phase 4). Building the slots now means turning on signing later is a config change.

**2.5 Basic web dashboard**
- **Auth + single-org model.** Stand up the dashboard with login and a single-organization data model (multi-site is Phase 4 — don't build it yet, but don't make single-org assumptions that are painful to unwind). Keep the schema's "org/site" boundary explicit even if there's one of each for now.
- **Announcement CRUD.** Forms to create/edit/delete announcements: pick a source, set a schedule, choose the target (multicast channel or SIP paging extension). This is where the source/driver pluggability surfaces to the user as dropdowns.
- **Agent status view.** Surface the heartbeat as a simple online/offline indicator with last-seen. This is the first thing an admin checks when "the announcements stopped," so make it prominent.
- **Test-announcement button.** A one-click "fire a test page now" that runs the full pipeline to the configured target. Invaluable during onboarding and support, and it's the manual trigger from Phase 1 promoted into the UI.

**2.6 Scheduler (time-driven)**
- **APScheduler-based firing.** Implement time-driven scheduling with per-site timezone awareness (single site for now). Cron-style entries: an 8:30 AM weather briefing, a post-close stock summary. This is the productized version of Phase 1's manual/stub trigger.
- **Dispatch path.** Define the runtime flow clearly: scheduler fires → content engine generates → TTS → encode → push to agent over WSS → driver delivers. Keep this path identical regardless of source or driver, so later additions (calendar triggers, new sources) reuse it untouched.

### Key deliverables
- A Go agent deployable as a native installer or a Docker container.
- Two working delivery drivers (multicast + SIP), SIP validated against Asterisk-in-Docker.
- A web dashboard that schedules/manages announcements and shows agent health.
- A CI pipeline producing all-target builds with signing slots ready.

### Exit criteria
- ✅ The agent installs from a single installer and auto-starts as a service.
- ✅ A scheduled announcement fires from the cloud and plays via **both** multicast and SIP paths (SIP validated against Asterisk-in-Docker + softphone).
- ✅ The dashboard shows the agent as online and can trigger a test page.
- ✅ CI produces Windows + Linux x86-64 builds on each release.

### Risks & mitigations
- *SIP/RTP in Go is unfamiliar* → spike the SIP registration + media path as a standalone Go program before integrating into the agent; lean on a mature SIP library rather than hand-rolling.
- *Per-OS service wrappers are fiddly* → start with Linux `systemd` (simplest), add the Windows service next; defer macOS `launchd` until a customer needs it.
- *Code-signing bureaucracy* → stub the signing steps in CI now; begin cert acquisition (long lead time) early in Phase 4, before public distribution.
- *Cloud↔agent contract churn* → freeze the `shared/` schema early and version it; uncoordinated changes here break both sides at once.

---

## Phase 3 — Feature Depth: Sources, Documents, Prompt Control (6–10 weeks)

**Objective:** Build out what makes the product genuinely useful day-to-day — the richer content sources, the document-input pipeline, the calendar (including event-driven triggers), and the admin-facing AI controls (prompt layer + config chatbot).

### Workstreams

**3.1 Calendar source + event-driven triggers**
- **Calendar source abstraction (query by date).** Implement the calendar as a structured content source — `fetch_events(date) → [events]` — feeding the engine like weather or stocks. The load-bearing decision: a calendar is *structured data queried by date*, never a RAG document. Querying by date is deterministic and reliable; semantic search over a calendar would be strictly worse. Enforce this by making the source's only query path date-based.
- **Connect-existing path (high value).** Add Google Calendar and Microsoft 365/Outlook via OAuth (the same "connect your account" flow as cloud-PBX), plus support for iCal/`.ics` subscribe-able feed URLs. The connect-existing path is the high-value version because it needs *zero ongoing data entry* — the calendar the office already maintains becomes the source. Start with iCal feeds (no OAuth consent screens) to prove the source, then layer in the OAuth providers.
- **In-app calendar (secondary).** A simple dashboard calendar for admin-entered events, for announcement-specific recurring reminders they wouldn't put on the company calendar. Lower priority — build it after the connect-existing path, since most offices already have a calendar.
- **Event-driven look-ahead loop (the headline).** Extend the Phase 2 scheduler so it doesn't only run fixed clock-time jobs: a periodic loop polls the calendar source for upcoming events matching a rule (e.g. tagged all-hands), computes each fire time as `event_start − offset`, and dynamically registers a job for it. This turns the calendar from passive content into an *active trigger* — the standout capability of the phase. Quiet hours and priority (Phase 4) still gate these dynamic jobs.
- **Why it touches the scheduler, not just sources:** time-driven and event-driven jobs converge on the same dispatch path, but event-driven requires the scheduler to look forward and self-populate jobs — the one genuinely new mechanism here.

**3.2 Document input pipeline (small-doc path)**
- **Ingest + validate.** Accept an upload, check extension and MIME type, and enforce a size cap. Route to the correct extractor by type — this is the only stage that cares about file format; everything after it is format-blind.
- **Format-specific extractors.** `.txt` read directly (already plain text); `.docx` via `python-docx` (pull paragraph text from the XML bundle); digital `.pdf` via `pypdf`/`pdfplumber` (text-layer extraction). These three are the clean, high-reliability formats — they cover the overwhelming majority of what an admin drops in (a memo, an events list, a one-pager).
- **Digital-vs-scanned guard.** If a PDF yields little or no text, it's probably a scanned image with no text layer — flag it back to the admin ("couldn't read this PDF, it may be a scan") rather than silently returning empty. OCR is the future path that would handle scans; don't build it now.
- **Normalize.** Collapse whitespace, strip control characters, normalize to UTF-8, drop boilerplate fragments → a clean text blob plus metadata (filename, upload time, source). After this point the text is just text, regardless of where it came from.
- **Size decision → whole-doc injection.** Branch on size: small docs (the common office case — a page or two) get injected *whole* into the Gemma prompt with no chunking, embeddings, or vector store. This is simpler, more accurate, and zero-infrastructure. Explicitly **defer the pgvector retrieval path** to a stub — building heavy RAG for documents that fit in context anyway is the over-engineering trap this design avoids.

**3.3 Prompt layer (layered system prompt)**
- **Three-layer assembly.** Implement prompt construction as concatenation of: a fixed **envelope** layer you own (output-format contract, length ceiling, speech-formatting rules, safety) + an editable **voice & priorities** layer the admin writes + a runtime **source context** layer (the actual data). The engine assembles all three; the admin edits only the middle one.
- **Editable layer UI with presets.** A dashboard editor for the voice layer, seeded with named presets (Professional / Friendly / Concise) so admins aren't staring at a blank box. The preset populates only the editable layer — the envelope stays hidden and intact.
- **Validation/guardrails.** Cap the admin text length, strip or escape envelope-override attempts (treat the admin layer as guidance *inside* the system contract, not a peer that can cancel "return only the announcement text"), and provide a **live preview** that generates a sample announcement from the current layers so the admin hears the effect before saving. Test with adversarial admin input ("ignore previous instructions…").
- **Per-type overrides.** Allow an announcement type to override the office default voice — e.g. emergency alerts force a serious tone regardless of a playful house style. This keeps a fun default from undermining a critical message.

**3.4 Config-authoring chatbot**
- **Natural-language → structured config.** A conversational surface where an admin describes standing rules ("every morning announce weather, remind about the 10am standup on weekdays, mention birthdays"), and Gemma emits **structured JSON** matching the announcement-config schema. Use the structured-output discipline: assign the role, give the literal schema, and extract-then-validate — never trust the raw string.
- **Render config back as editable fields.** Show the produced configuration as reviewable, editable form fields, not as opaque chat. The admin sees exactly what will be scheduled and can tweak before saving. This is what keeps the system from becoming a black box.
- **Authoring vs runtime separation (reinforce it).** The chatbot *authors* config; the scheduler *executes* the saved structured rules — the chat transcript is never replayed at fire time. Keep these two phases architecturally distinct; conflating them is the main design mistake to avoid here.

**3.5 Source enrichment (optional, demand-driven)**
- **Weather upgrade.** Swap `wttr.in` for OpenWeatherMap (keyed) when you want richer, more reliable data — a drop-in behind the existing weather fetcher dict shape, no engine/prompt change.
- **Licensed stock provider.** Replace `yfinance` with Finnhub or Alpha Vantage (free tiers) when reliability and ToS matter — again isolated behind the fetcher interface, so nothing downstream moves. This is the "prototype-now / license-later" swap the stock source was designed around.
- **News/sports (future).** Note these as future sources following the same fetcher+prompt pattern, but each needs a content-governance layer (news: copyright-safe summarization + editorial source controls; sports: favorite-team config + recap-vs-live timing). Don't build them this phase; record the rules so they're not afterthoughts when you do.

### Key deliverables
- Calendar-driven announcements, both time-driven and event-driven.
- A working document-drop feature for `.txt`/`.docx`/digital `.pdf` with whole-doc injection.
- An admin prompt-customization UI with presets and live preview.
- A natural-language config chatbot that produces reviewable, editable rules.

### Exit criteria
- ✅ An announcement fires 15 minutes before a calendar event via the event-driven trigger.
- ✅ A dropped-in `.docx` of this week's events is read out in an announcement.
- ✅ An admin can change the announcement voice via a preset and hear the difference in preview.
- ✅ The config chatbot turns a plain-English request into a saved, editable announcement rule.

### Risks & mitigations
- *Calendar OAuth scope creep / consent screens* → start with iCal feeds (no OAuth) to prove the source end to end, then add Google/365 OAuth providers.
- *Admins editing the prompt break output* → the envelope layer plus validation is the safeguard; explicitly test adversarial admin input against the envelope contract.
- *Chatbot produces invalid config* → extract-then-validate with strict schema enforcement; never auto-save — require admin confirmation of the rendered fields.
- *Over-engineering RAG* → explicitly defer pgvector to a stub; whole-doc injection covers the common case, and the retrieval path is added only when document volume demands it.

---

## Phase 4 — Harden, Secure, Scale, Sell (8–12 weeks)

**Objective:** Make it enterprise-ready and sellable — security posture, admin safety controls, multi-site, monitoring, the full build matrix, cloud-PBX integrations, and the commercial plumbing.

### Workstreams

**4.1 Security pass**
- **Encrypt the SIP path.** Add TLS for SIP signaling and SRTP for the media so paging audio and call setup aren't in the clear on the customer network. Enterprise security reviews will ask for this explicitly; it's not optional for selling into companies with a review process.
- **Encrypt cloud↔agent everywhere.** Enforce HTTPS/WSS for all cloud-agent traffic and encrypt audio in transit. Audit that no announcement audio or credential ever traverses a plaintext channel.
- **Secrets hygiene.** Scoped, revocable per-site credentials; no plaintext secrets at rest; integrate with the hosting platform's secret store (the Phase 0 "env-vars only" discipline pays off here). Add rotation from the dashboard.
- **Acquire and wire real signing certs.** Authenticode certificate from a CA for Windows (plus building SmartScreen reputation), Apple Developer account + notarization for macOS, GPG-signed repos for Linux `.deb`/`.rpm`. Flip the Phase 2 placeholder signing steps to real certs. Start this early in the phase — cert issuance has real lead time.

**4.2 Admin safety controls**
- **Quiet hours.** Let admins block announcements outside business hours (e.g. nothing before 8 AM or after 6 PM). Enforce it in the scheduler/dispatch path so both time-driven and event-driven jobs respect it.
- **Kill switch.** A way to override or stop an in-progress announcement immediately — important because an automated voice is broadcasting to a physical room and an admin needs an emergency stop.
- **Approval workflow.** Gate announcement *types* before they go live, so a new automated source can't start paging the office without a human signing off.
- **Priority levels.** Ensure AI announcements never preempt a higher-priority human/emergency page — wire priority into both the multicast channel priority and the SIP/dispatch logic. This is a safety property, not just a nicety: a weather update must never talk over an emergency.

**4.3 Multi-site**
- **Per-site agent + config.** Formalize the model where each site runs its own agent with its own config, and sites can run different phone systems (one office multicast, another SIP, another cloud-PBX). The Phase 2 single-org schema's explicit site boundary makes this an extension rather than a rewrite.
- **Central management.** One dashboard managing all sites — per-site status, per-site scheduling, per-site agent health — so an admin for a multi-office company has a single pane of glass.

**4.4 Reliability & monitoring**
- **Heartbeat-driven status.** Surface online/offline + last-seen per site from the Phase 2 heartbeat, now across many sites. Make "the Denver agent went dark 20 minutes ago" obvious.
- **Queue/replay across outages.** Harden the agent's local queue so scheduled pages survive a brief cloud outage and replay (respecting the staleness policy) on reconnect.
- **Delivery logs + alerting.** Per-announcement delivery logs (fired, delivered, failed) for auditing and support, plus alerting when an agent goes offline so you find out before the customer does.

**4.5 Cloud-PBX integrations (zero on-prem segments)**
- **API drivers per platform.** Build delivery drivers for RingCentral, Zoom Phone, Microsoft Teams Phone, and 8x8 using each platform's API. Each one removes the on-prem agent entirely for that segment — the cloud talks straight to the platform — opening a market that needs zero local deployment.
- **OAuth account connection.** A per-provider OAuth flow so the customer just connects their account. Ship one provider fully, template the pattern (auth → initiate page → stream/play audio), then add the others by demand rather than all at once.

**4.6 Build matrix expansion**
- **Add Apple Silicon + ARM/Pi targets.** Extend the CI matrix to macOS ARM64 and Linux ARM64 as demand appears — Go makes the additional targets cheap to build, the cost is mostly testing and (for macOS) signing/notarization.
- **Pre-flashed appliance tier.** Offer a Raspberry Pi / mini-PC shipped pre-configured for the least-technical customers — plug in, it phones home, it's live. This collapses the whole build/deploy story to a single controlled target for those accounts, at the cost of hardware logistics (inventory, shipping, RMAs) — so price it as a premium "we handle everything" tier.

**4.7 Commercial plumbing**
- **Billing + plan tiers.** Integrate Stripe (or similar) for subscriptions, define plan tiers (e.g. AI-free template tier, standard, multi-site enterprise) and usage limits. The template-fallback path from Phase 1 makes a genuine no-AI tier possible.
- **Onboarding wizard.** Build the branching wizard from spec §6: ask "what phone system do you use?" and route to the right driver (multicast / SIP / cloud-PBX), collecting only the relevant connection details and a test page at the end. This is what makes "configure how to reach your phones" the single setup step.
- **Run somewhere real.** Move the cloud off a dev machine onto an always-on hosting platform (Railway/Render/Fly.io to start, the big three later) so scheduled announcements fire 24/7, agents have a stable address to phone home to, and data persists in a real database. This is the line between "a script I run" and "a service that runs."

### Key deliverables
- Encrypted, signed, monitored, multi-site product.
- At least one cloud-PBX integration live (no on-prem agent for that segment).
- Billing + the branching onboarding wizard.
- Expanded packaging including the pre-flashed appliance option.

### Exit criteria
- ✅ SIP paging runs over TLS/SRTP; installers are signed and pass OS gatekeepers (no "unknown developer" blocks).
- ✅ Quiet hours, kill switch, approval, and priority all enforce correctly.
- ✅ A second site can be managed from one dashboard.
- ✅ At least one cloud-PBX path pages with no on-prem agent.
- ✅ A new customer can sign up, onboard via the wizard, and be billed.

### Risks & mitigations
- *Cert acquisition lead time* → begin the Apple/Authenticode process at the *start* of the phase; it gates the signed-installer exit criterion.
- *Multi-site config complexity* → the per-site-agent model already isolates this; keep all config strictly per-site and avoid cross-site coupling.
- *Each cloud-PBX integration is its own effort* → ship one fully, extract the common pattern, add the rest by customer demand rather than speculatively.
- *Priority/quiet-hours bugs are high-stakes* → an AI page talking over an emergency is a serious failure; test priority enforcement hard, including the event-driven trigger path.

---

## Cross-Cutting Concerns (every phase)

- **Testing discipline.** The laptop test environment (spec §10) means almost everything is testable without office hardware — VLC for multicast playback, Asterisk-in-Docker + a softphone for SIP, Wireshark for packet inspection. Keep this harness working as the system grows; it's what lets you develop the whole product from a couch and ship the same code to real Yealink hardware unchanged.
- **Pluggability is the architectural through-line.** Sources, delivery drivers, TTS providers, and packaging formats are all interchangeable behind interfaces. Every new capability should slot into an existing interface, not bolt onto the side — if it can't, the interface is wrong and fixing it is the real task.
- **Defensive parsing is permanent.** Any LLM output is untrusted until validated — announcement scripts (trim/strip wrappers before TTS) *and* chatbot config JSON (extract-then-validate against the schema). This rule never relaxes, in any phase.
- **Authoring vs runtime separation.** Configuration is *authored* (via the chatbot and dashboard) into structured rules; the scheduler *executes* those rules. Never blur the two — the runtime must not depend on chat transcripts or unparsed intent.
- **Keep the agent thin.** All heavy lifting (AI, TTS, encoding) stays in the cloud; the agent receives finished audio and delivers it via a driver. Resist pushing logic into the agent — its thinness is what keeps it cheap to build per-platform and easy to deploy everywhere.

---

## Phase Dependency Summary

| Phase | Depends on | Unlocks |
|---|---|---|
| 0 — Spike | — | Confidence the core premise (synthesized RTP plays on a phone) works |
| 1 — Core | 0 | A working end-to-end pipeline on real hardware, with proven pluggability |
| 2 — Productize | 1 | A deployable product (Go agent, multicast + SIP drivers, dashboard, CI) |
| 3 — Features | 2 | Day-to-day usefulness (calendar + event triggers, docs, prompt control, chatbot) |
| 4 — Enterprise | 2 (security/scale), 3 (feature completeness) | A sellable, enterprise-ready SaaS |

The critical path runs 0 → 1 → 2. After Phase 2, feature depth (3) and enterprise hardening (4) both build on the same platform but address different needs — usefulness vs. sellability — so they can overlap. Sequence the overlap by whichever your earliest customers demand first: a design partner who needs calendar integration pulls Phase 3 forward; a security-conscious enterprise buyer pulls Phase 4's encryption and signing forward.
