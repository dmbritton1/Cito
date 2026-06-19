# AI Office Paging System — Technical Specification & Architecture

A SaaS product that delivers AI-generated announcements (weather, reminders, alerts) through existing office IP phone systems. This document captures the architecture, components, and build plan.

---

## 1. Product Overview

### What it does
Generates spoken announcements with AI and broadcasts them out of office desk-phone speakers — automatically and on a schedule. Example: an 8:30 AM weather briefing, midday meeting reminders, end-of-day notices.

### Core design principle
**The only thing a customer must configure is how to reach their phones** (a multicast address, SIP credentials, or a cloud-PBX connection). Everything upstream — content generation, text-to-speech, scheduling, audio formatting — is self-contained and identical across every deployment.

### Target outcome
Drop-in announcement automation that works across multiple phone brands and network setups, deployable by an IT admin in minutes.

---

## 2. High-Level Architecture

The system uses a **hybrid cloud + on-prem agent** model. The cloud owns the intelligence; a lightweight on-prem agent owns the "last mile" of getting audio onto the phones.

```
┌─────────────────────────── CLOUD (SaaS) ───────────────────────────┐
│                                                                     │
│   Web Dashboard  →  Scheduler  →  Content Engine (AI)  →  TTS       │
│        │                                    │              │        │
│   User / Site / Billing mgmt          Weather & data    Audio file  │
│                                          sources         (encoded)  │
│                                                            │        │
└────────────────────────────────────────────────────────────┼───────┘
                                                              │
                                            HTTPS / WSS (encrypted)
                                                              │
┌─────────────────────────── ON-PREM AGENT ───────────────────┼───────┐
│                                                              ▼       │
│   Receives audio  →  Delivery driver (selected per customer)         │
│                          ├── Multicast RTP driver                    │
│                          ├── SIP paging driver                       │
│                          └── Cloud-PBX API driver                    │
│                                      │                               │
└──────────────────────────────────────┼──────────────────────────────┘
                                        ▼
                              Desk phones (speakers)
```

### Why this split
- **VLAN/firewall problems disappear** — the agent is deployed where the phones already live (the voice VLAN), so it doesn't have to cross network boundaries.
- **Brand/PBX differences are isolated** to the agent's delivery drivers, like a printer-driver model. The cloud never needs to know what phones a customer runs.
- **No audio streaming burden on the cloud** — the cloud ships a finished, compact audio file; the agent handles real-time packet pacing locally.

---

## 3. Cloud Platform Components

### 3.1 Web Dashboard
Admin-facing SaaS UI. Responsibilities:
- Manage announcement types (weather, stock market, calendar/events, reminders, custom messages, emergency alerts)
- Customize the **editable prompt layer** (voice & priorities) with presets and live preview (see §3.3.1)
- Author standing announcement rules via the **config chatbot** (see §3.3.2)
- Connect a **calendar** (Google / Microsoft 365 / iCal) or use the in-app calendar (see §3.6)
- Drop in **context documents** (see §3.7)
- Build and edit schedules
- Multi-site management (one pane of glass across office locations)
- Agent health/status monitoring
- User management, roles, billing

### 3.2 Scheduler
The scheduler supports **two trigger types**:

**Time-driven (fixed clock times)** — the default. Fires announcements at configured times (cron-style), e.g. an 8:30 AM weather briefing or a post-4 PM market summary.
- Per-site timezone awareness
- Respects quiet hours and priority rules before dispatching

**Event-driven (relative to calendar events)** — fires an announcement at a time *computed from an event*, e.g. "15 minutes before any meeting tagged all-hands." This requires a **look-ahead loop**: the scheduler periodically polls the calendar source (§3.6) for upcoming qualifying events, computes each fire time (event start − offset), and dynamically registers a job for it — rather than only running a static list of clock-time jobs. Quiet hours and priority still apply.

Both trigger types converge on the same dispatch path into the content engine, so all downstream machinery (prompt layer, quiet hours, priority, delivery) is identical regardless of how the announcement was triggered.

### 3.3 Content Engine (AI)
- Pulls source data from a **pluggable set of content sources** (weather, stock market, etc.)
- Uses an LLM to turn raw structured data into a natural, brief spoken script
- Example transform: `{temp: 92, condition: sunny}` → *"Good morning everyone, it's going to be 92 and sunny today..."*
- Template fallback when no LLM key is configured (keeps the product usable without AI)

Each content source is just a **fetcher + prompt template** feeding the same engine; everything downstream (TTS, encoding, delivery, scheduling, quiet hours, priority) is identical regardless of source. Adding a source = adding a fetcher and a prompt, nothing else. See §3.6 for the source catalog.

**Provider: Gemma 4 (`gemma-4-26b-a4b-it`) via the Gemini API**, called over **direct REST from Python** (no SDK). Rationale: the integration is a single endpoint ("data in → script out"), so an SDK is overkill and the Node-only `@google/genai` would otherwise split the cloud across two languages. A plain `httpx`/`requests` POST keeps the entire cloud in Python with no dependency to maintain. Auth is a `GEMINI_API_KEY` (already provisioned via AI Studio).
- Keep the model id in **one constant** so swapping models/providers is a one-line edit.
- **Defensive parsing is mandatory** (language-independent): the model output is *untrusted text* until cleaned. Trim and strip wrapping quotes/fences before handing the script to TTS — otherwise phones may literally speak a wrapper like *"Here's your weather update:"*. For any structured output, extract-then-validate rather than trusting the raw string.
- If the content engine later grows complex (heavy prompt logic, own deploy cadence), it can be promoted to a standalone service without unpicking the backend — the integration is just "POST to an endpoint, parse text."

#### 3.3.1 Prompt Layer (Layered System Prompt)

The dashboard lets admins shape *how* announcements sound and *what* they prioritize — without exposing the load-bearing machinery that keeps output announceable. The mechanism is a **layered prompt**: the engine concatenates layers at generation time, but the admin only edits the middle one.

**The layers (assembled in order):**

| Layer | Owner | Editable? | Contains |
|---|---|---|---|
| **System / envelope** | Product (us) | No (hidden) | Output-format contract ("return only the announcement text, no preamble"), length ceiling, speech-formatting rules (spell-friendly numbers, no markdown), safety rails |
| **Voice & priorities** | Admin | Yes | Tone, personality, content focus — e.g. *"Keep it upbeat and brief, always mention weather first, we're a casual office so a little humor is welcome."* |
| **Source context** | Engine (runtime) | No (generated) | The actual data for this announcement — weather payload, stock quotes, dropped-in doc text, calendar events |

**Why the split matters.** The envelope layer is what prevents the failure modes already established in §3.3 — if an admin could edit "return only the announcement text," they could accidentally remove it and phones would start speaking *"Here's your update:"* or markdown asterisks. So the admin gets full control of voice and content emphasis while the engine **guarantees** the result stays a clean, short, speakable string. The admin layer is additive guidance; it cannot override the envelope contract.

**Presets over a blank box.** A blank prompt field is intimidating and most admins don't know what good prompt text looks like. Ship named presets — *Professional*, *Friendly*, *Concise* — as starting points the admin can use as-is or edit. The preset populates only the editable voice layer.

**Validation / guardrails on the editable layer:**
- Length cap on the admin text (a prompt isn't a document)
- Strip or escape anything that looks like an attempt to break the envelope (e.g. injected "ignore previous instructions" / format-override text) — treat the admin layer as *guidance appended inside* the system contract, not as a peer to it
- Live preview: generate a sample announcement from the current layers so the admin hears the effect before saving
- Per-announcement-type override allowed (the emergency-alert type might force a serious tone regardless of the office's default playful voice)

#### 3.3.2 Config-Authoring Chatbot

A conversational way for admins to set up **standing announcement rules** in natural language, instead of filling out forms. *"Every morning announce the weather, remind everyone about the 10am standup on weekdays, and mention birthdays"* → the system produces structured, reviewable announcement configs.

**The critical distinction — authoring vs runtime.** The chatbot is a **config-authoring assistant**, not the announcement runtime. It does **not** get replayed at 8:30 AM. It translates intent into structured announcement objects (source, schedule, priority, prompt additions) that the admin reviews and confirms; at fire time the **scheduler runs those structured rules**, never the chat transcript. Keeping these two phases separate is essential — otherwise the system becomes a black box where nobody can see what's actually scheduled to play.

**How it works:**
- Feed Gemma the admin's message **plus a description of the config schema**, and have it emit structured JSON populating the announcement settings — the "structured output" pattern (assign role, give the literal schema, **extract-then-validate**, never trust the raw string).
- Render the produced config back to the admin as **editable fields**, not as opaque chat — they see exactly what will be scheduled and can tweak before saving.
- The chatbot writes config; the dashboard's normal scheduling/quiet-hours/priority controls still govern execution.

> Net: the editable prompt layer controls *how things are said*; the config-authoring chatbot controls *what is announced and when*; the source context (§3.6) and document pipeline (§3.7) control *what facts* the announcement draws on. Three separate concerns, deliberately not conflated.

### 3.4 Text-to-Speech (TTS)
- Converts the script to audio
- Pluggable providers: ElevenLabs (most natural), Google Cloud TTS, Amazon Polly, or offline engines for cost-sensitive tiers
- Output normalized to a known high-quality format before encoding

### 3.5 Audio Encoder
- Converts TTS output to the phone-ready format **before** sending to the agent (keeps the agent thin)
- Target: **G.711 µ-law (PCMU), 8 kHz, mono** by default; **A-law (PCMA)** for non-NA regions; optional **G.722** wideband for newer phones
- ffmpeg under the hood

### 3.6 Content Sources

Each source implements a common interface — `fetch() → structured data`, paired with a source-specific Gemma prompt. New sources slot in without touching the rest of the engine.

#### Weather
- Source: OpenWeatherMap / WeatherAPI (keyed); `wttr.in` (keyless) for prototyping
- Fire-and-forget: today's forecast stands alone, no prior-state dependency
- Prompt produces a brief, friendly forecast line

#### Stock Market
The market feature is the same pipeline as weather (fetch → Gemma → TTS → deliver) with a few domain-specific rules that must be designed in:

**Data source — pluggable, prototype-now / license-later.**
- **Prototype:** `yfinance` (Python) — free, no account, pulls quotes + previous close in a few lines. Note it's an *unofficial* library over Yahoo's public endpoints: endpoints can change without notice and the data isn't guaranteed, so it's scaffolding, not a foundation.
- **Production:** a **licensed** provider — Finnhub or Alpha Vantage (free tiers) to start, Polygon.io or Twelve Data at scale. Stable endpoints, terms that permit commercial use, support.
- Because the source is isolated behind the fetcher interface, swapping `yfinance` → licensed provider is a one-module change; nothing downstream moves.

**Announce the *change*, not the absolute number.** "Apple is at $228" is noise; "Apple is up 1.2% today" is the signal. The fetcher must pull current price **and** previous close / day change, not just the spot price (most quote endpoints return all three in one call).

**Market-hours awareness.** Unlike weather, stock data has open/closed state (≈9:30 AM–4:00 PM ET, weekdays, minus holidays). Each announcement must declare what it *means*:
- *Pre-market briefing* — prior close + futures
- *Market-close summary* — final numbers for the day **(recommended first version — data is final, unambiguous, sidesteps "is the market open")**
- *Midday check-in* — live intraday state
Handle weekends/holidays (stale-data guard) so a Tuesday-after-a-holiday page doesn't read Friday's close as "today."

**What to announce (speech is linear — keep it short).**
- *Watchlist*: admin-configured tickers (company's own stock, a few of interest); ~5–6 max before listeners tune out
- *Indices for context*: lead with S&P 500 / Nasdaq direction as a one-line "market mood"
- *Threshold / "only if interesting"*: optionally mention a name only if it moved beyond a set % (e.g. ±3%), so flat days stay short and volatile days expand

**Gemma rules specific to stocks (bake into the prompt):**
- **Round to speech-friendly precision** — "up about 1.2 percent," never "up 1.234 percent"
- **Say company names, not tickers** — "Apple," not "A-A-P-L" (otherwise TTS spells letters)
- Vary verbs (gained / slipped / jumped / fell) and group winners vs losers for natural delivery

**Compliance note.** Public prices as an internal FYI are low-risk. If this is ever sold/pointed outside your own office, financial info carries a different liability profile than weather: keep announcements **descriptive** ("Apple is up 1.2%"), never **advisory** ("Apple is a buy"), and include a "for informational purposes, not financial advice" disclaimer. Worth knowing the line exists before crossing it.

#### Calendar
The calendar is a **structured content source queried by date**, not a RAG document — this distinction is the whole design. RAG fuzzily searches unstructured text; a calendar answers a precise question ("what's on today?") with an exact, deterministic result (events whose date = today). Treating it as RAG would make it *less* reliable. So the calendar is a sibling to weather and stocks: structured data in → Gemma → script → phones.

**Getting data in — two ways:**
- **Connect an existing calendar (high-value path):** the admin connects Google Calendar or Microsoft 365/Outlook via **OAuth** (same "connect your account" flow as the cloud-PBX integrations), then the system queries the day's events. Best because it needs **zero ongoing data entry** — the calendar they already maintain becomes the source. Also support the **iCal/`.ics`** subscribe-able URL standard for broad compatibility without a per-provider integration.
- **Build an in-app calendar (secondary path):** admin enters events directly in the dashboard. Lower value when an office already has a calendar (two to maintain), but useful for announcement-specific recurring reminders they wouldn't put on the company calendar.

**Two ways the calendar feeds the system (see §3.2):**
- **As content (time-driven):** at a fixed scheduled time, query "today's events" and announce them — identical in shape to weather/stocks.
- **As trigger (event-driven):** the announcement *time* is computed from an event (e.g. event start − 15 min). The calendar drives the schedule itself via the scheduler's look-ahead loop. This is the standout capability — it turns the calendar from passive content into an active trigger source.

> Net mechanism: both calendar inputs feed one **calendar source** abstraction (query by date); everything downstream is identical regardless of which input the events came from — the same pluggable pattern as every other source.

> Sources can also **combine** into one announcement — e.g. a morning briefing that reads weather, then a market-open summary, then "and three meetings on the calendar today" — since they share the engine and the script is just concatenated context to Gemma.

### 3.7 Document Input Pipeline (Dropped-in Files)

Admins can drop in files to give announcements real context (a memo, an events list, a policy note). Supported formats at launch are the **clean, structured** ones — `.txt`, `.docx`, and **digital** `.pdf` — chosen because text is cleanly retrievable with high reliability and no OCR. Scanned/image PDFs and other formats are a later, opt-in addition.

**Core principle — extraction is the only format-specific step.** Once a file is reduced to plain text, everything downstream (size check, optional retrieval, prompt assembly, Gemma, TTS, delivery) is format-blind. A sentence from a `.docx` and a sentence from a `.pdf` are identical as text. So the pipeline isolates all format knowledge in one stage and treats the rest generically.

#### Stage 1 — Ingest & validate
- Accept upload; check extension + MIME type; enforce a size cap
- Route to the correct extractor by type (the only branch that cares about format)

#### Stage 2 — Extract to plain text (format-specific)
| Format | Method | Reliability |
|---|---|---|
| `.txt` | Read directly — already plain text | Trivial / always works |
| `.docx` | `python-docx` (or Tika/Docling) — pull paragraph text from the XML bundle | High — structured, clean |
| `.pdf` (digital) | Text-layer extraction (e.g. `pypdf`/`pdfplumber`) | High when a text layer exists |

> **Digital-vs-scanned guard:** if a PDF yields little or no text, it's likely a scan (an image with no text layer). At launch, flag it back to the admin as "couldn't read this PDF — it may be a scan" rather than silently returning empty. OCR is the future path that would handle this case.

#### Stage 3 — Normalize
- Collapse whitespace, strip control characters, normalize encoding to UTF-8
- Drop empty/boilerplate fragments
- Result: a clean text blob + metadata (filename, source, upload time)

#### Stage 4 — Size decision (the tiering branch) ⭐
The pivotal step that avoids over-engineering:
- **Small doc (fits in context):** inject the **whole text** into the Gemma prompt. No chunking, no embeddings, no vector store. Simpler, more accurate, zero infrastructure. **This is the common case** for office announcements (a page or two).
- **Large / many docs (exceeds budget):** fall through to the retrieval path (Stage 5).

A token/character threshold (tuned to the prompt budget) decides the branch. Most dropped-in announcement files take the small-doc path.

#### Stage 5 — Retrieval path (only when needed)
For content too large to inject wholesale. Clean-room implementation (see note) using the architecture Open WebUI validates in production:
1. **Chunk** the normalized text (size + overlap)
2. **Embed** each chunk (Gemini embeddings endpoint — same Google auth already in use)
3. **Store** vectors in **pgvector** (Postgres extension — reuses the app DB; no separate vector service to start)
4. At announcement time: **embed the query → retrieve top-k relevant chunks → prepend to the prompt**

> **Licensing note:** the RAG architecture mirrors Open WebUI's proven component choices, but its code is **not** copied. Open WebUI ships under a custom license with a branding-retention clause unsuitable for embedding in a commercial product, so this path is built clean-room on permissively-licensed libraries (Tika/Docling for extraction, pgvector for storage). Use Open WebUI as a **reference architecture, not a code source.**

#### Stage 6 — Prompt assembly & retention
- Hand the assembled context (whole small doc, or retrieved chunks) to the content engine alongside the editable prompt
- Apply the same **defensive parsing** before TTS
- Retain the source doc per admin policy (re-usable across announcements; deletable on demand)

**Build order:** Stages 1–4 + 6 (extraction + whole-doc injection) ship first and cover most real use. Stage 5 (pgvector retrieval) is added only when document volume demands it — not on day one.

---

## 4. On-Prem Agent

A lightweight service the customer deploys on their voice network. Same core everywhere; behavior varies only by which **delivery driver** is active.

### 4.1 Responsibilities
- Authenticate to the cloud; maintain a persistent connection (WSS) and heartbeat
- Receive encoded audio + delivery metadata
- Hand audio to the configured delivery driver
- Cache scheduled announcements locally so it can fire even during a brief cloud outage
- Report status/errors back to the dashboard

### 4.2 Packaging & Distribution

The agent ships in multiple forms, and the right one depends on **who is installing it**. There's a fundamental trade between customer setup effort and our own maintenance burden: the easier we make install for the customer, the more build/packaging work we absorb. The strategy is to offer a small set of options and steer each buyer to the one that fits.

#### Form factors (least → most customer setup)
| Form factor | Customer setup | Our burden | Best for |
|---|---|---|---|
| **Pre-flashed hardware appliance** (Pi / mini PC) | Plug into voice network, powers on, phones home | Hardware logistics: inventory, shipping, RMAs. Single OS/arch to build for | Least-technical / no-IT small offices; premium "we handle everything" tier |
| **Native single-binary installer** (`.msi` / `.pkg` / `.deb`/`.rpm`) | Double-click, Next, enter connection details. Installs as auto-starting background service | Build + sign + test **per OS/arch** (see below) | **Default for most offices** — clean install, no assumed infrastructure |
| **Bootable OS image** (Pi / mini PC, customer-supplied hardware) | Flash with Raspberry Pi Imager, boot | Maintain one image; no hardware logistics | Small offices comfortable flashing an SD card/USB |
| **Docker container** | Needs a Docker host; deploy onto any VLAN | Build **one** image, runs anywhere with a runtime | Technical IT shops that already run Docker (they'll ask for it) |
| **VM appliance (OVA)** | Import into VMware/Hyper-V (few clicks *if* infra exists) | Maintain one image | Enterprises already running virtualization |
| **No agent at all** | OAuth connection only | None on-prem | Cloud-PBX customers (RingCentral/Zoom/Teams/8x8); optionally remote-SIP customers |

**Recommended default:** lead with the **native single-binary installer** — it gives the double-click experience of an appliance without us shipping hardware, and assumes no existing infrastructure (unlike Docker/OVA). Keep **Docker** as the option for technical customers, and the **pre-flashed appliance** as the premium hands-off tier. Cloud-PBX customers get nothing to install.

> **Match packaging to buyer:** non-technical small office → installer or appliance · mid-size IT → installer or Docker · VMware enterprise → OVA or Docker · cloud-PBX → nothing. Same agent core underneath, wrapped differently.

#### Write the agent in Go (not Python)
Although the cloud stack is Python, the **on-prem agent should be written in Go** (Rust is a fair alternative). The agent's entire value proposition is "easy to deploy everywhere," and Go delivers exactly that:
- **Clean cross-compilation** — every OS/arch target builds from one machine with one command (`GOOS`/`GOARCH`), unlike PyInstaller, which **cannot cross-compile** and would force a separate build machine per OS.
- **Standalone static binary** — no runtime for the customer to install, which is what makes the single-binary installer experience possible.

The Python audio/encoding work stays in the cloud (where the heavy lifting already happens); the agent just receives encoded audio and runs the delivery driver, so a lean Go agent fits naturally.

#### The build matrix (cost behind "single binary")
A compiled binary only runs on the OS + CPU architecture it was built for, so "one binary" really means a matrix:

| OS | Arch | Notes |
|---|---|---|
| Windows | x86-64 | Most common office target |
| Windows | ARM64 | Newer ARM Windows; small but growing |
| macOS | x86-64 | Older Intel Macs |
| macOS | ARM64 | Apple Silicon |
| Linux | x86-64 | Most servers / mini PCs |
| Linux | ARM64 | Raspberry Pi / ARM mini PCs |

Managing this matrix:
- **CI runs the matrix** — GitHub Actions (or similar) builds and signs all targets automatically on each release; no rack of build machines.
- **Narrow initial support** — launch with Windows + Linux x86-64 (where voice-network hosts usually live); add Apple Silicon and ARM/Pi builds as demand appears.
- **Per-OS code signing** is the underestimated cost and must be wired into each build:
  - *Windows* — Authenticode cert from a CA (~hundreds/yr) + SmartScreen reputation.
  - *macOS* — Apple Developer account ($99/yr), signing, **and** notarization (upload each build to Apple).
  - *Linux* — no mandatory signing; GPG-sign `.deb`/`.rpm` repos.
- **Per-OS service wrapper** to auto-start on boot: Windows Service Control Manager · macOS `launchd` plist · Linux `systemd` unit. Each installer registers the agent as a proper background service for that OS.

> The appliance/pre-flashed model collapses this entire matrix to a **single controlled target**, which is part of why it's attractive for the least-technical tier despite the hardware logistics.

### 4.3 Delivery Drivers

#### Driver A — Multicast RTP (direct to phones)
- Sends one RTP stream to a multicast group; the network fans it out to all subscribed phones
- No PBX involvement; scales to many phones with a single stream
- Per-brand config lookup table (default multicast ports etc.) for Yealink, Poly, Cisco SPA, Grandstream, Snom, Fanvil
- **Customer config needed:** multicast address + port, codec (region default)

#### Driver B — SIP Paging (through the PBX)
- Agent registers as a SIP extension on the customer's PBX
- "Dials" the existing paging-group extension; PBX fans audio out to phones
- Works with **any** SIP PBX regardless of phone brand; sidesteps VLAN concerns entirely (PBX already reaches every phone)
- **Customer config needed:** PBX address, SIP username, SIP password, paging extension

#### Driver C — Cloud-PBX API
- For hosted phone systems (RingCentral, Zoom Phone, Teams Phone, 8x8)
- Uses the platform's REST API to initiate the page; **no on-prem agent required** for these customers
- **Customer config needed:** OAuth connection to their account

---

## 5. The Audio Pipeline (End to End)

How a single announcement travels from idea to phone speaker:

1. **Source data** — fetch weather (or other content) from an API.
2. **Script generation** — LLM writes a short, natural announcement.
3. **TTS** — script becomes high-quality audio (MP3/WAV, 44.1 kHz, 16-bit).
4. **Encode** — ffmpeg downsamples to 8 kHz mono and applies µ-law/A-law companding → raw headerless audio (8,000 bytes/sec).
5. **Packetize (agent, RTP path)** — slice into 160-byte chunks (= 20 ms each), prepend a 12-byte RTP header → 172-byte packets.
6. **Stream** — send each packet over UDP every 20 ms to the multicast address (or into the SIP call's RTP stream).
7. **Playback** — phones pull packets into a jitter buffer, decode µ-law back to PCM, and drive the speaker.

**Reference:** a 10-second announcement ≈ 500 packets, ~84 KB total, ~60–100 ms end-to-end latency.

---

## 6. Setup / Onboarding Flow

A wizard branches on the customer's phone system so they only ever see relevant fields.

1. Sign up on the dashboard.
2. **"What phone system do you use?"**
   - On-prem PBX (FreePBX/Asterisk/Cisco/etc.) → offer **SIP** or **Multicast** driver
   - Direct-to-phone multicast → **Multicast** driver
   - Cloud PBX (RingCentral/Zoom/Teams/8x8) → **API** driver, no agent
3. Download + deploy the agent (Docker/VM/Pi) — *skipped for cloud-PBX path*.
4. Enter the one set of connection details for the chosen driver.
5. Send a test announcement to a single phone/softphone to confirm.
6. Build schedules and go live.

---

## 7. Enterprise Requirements

### 7.1 Security
- TLS + SRTP for SIP paging (encrypted signaling + media)
- HTTPS/WSS for all cloud ↔ agent traffic
- Encrypted audio in transit
- Scoped credentials; no plaintext secrets at rest

### 7.2 Admin Controls
- **Quiet hours** — block announcements outside business hours
- **Kill switch** — override/stop an in-progress announcement
- **Approval** — gate announcement types before they go live
- **Priority levels** — AI announcements must never preempt a human emergency page

### 7.3 Multi-Site
- Each site runs its own agent + config (can be different phone systems per site)
- Central dashboard manages all sites together

### 7.4 Reliability & Monitoring
- Agent heartbeats; dashboard shows online/offline + last-seen per site
- Local queue/replay so a brief cloud outage doesn't drop scheduled pages
- Delivery logs per announcement

---

## 8. Suggested Tech Stack

| Layer | Choice |
|---|---|
| Glue / services | Python |
| Content data | Weather API (e.g. wttr.in free tier, OpenWeatherMap) |
| Stock data | `yfinance` (prototype) → Finnhub / Alpha Vantage / Polygon / Twelve Data (licensed, production) |
| Calendar | Google Calendar / Microsoft 365 APIs via OAuth · iCal/`.ics` feeds · in-app calendar |
| Doc extraction | `.txt` direct · `.docx` via `python-docx` (or Tika/Docling) · digital `.pdf` via `pypdf`/`pdfplumber` |
| RAG (when needed) | Gemini embeddings + **pgvector** (Postgres); chunk-embed-retrieve, clean-room (Open WebUI as reference only) |
| AI scripting | Gemma 4 (`gemma-4-26b-a4b-it`) via Gemini API, **direct REST from Python** (`httpx`); template fallback |
| TTS | ElevenLabs / Google Cloud TTS / Polly (pluggable) |
| Audio encoding | ffmpeg (cloud-side) |
| Cloud services | Python |
| **On-prem agent** | **Go** (single static binary, clean cross-compile; Rust alternative) |
| RTP streaming | raw packets (UDP) in the agent; SIP path via a SIP/RTP library |
| SIP client | PJSIP-class library (Go SIP stack or cgo binding) |
| Scheduling | APScheduler (cloud) |
| Agent packaging | Native installer (default), Docker, OVA, pre-flashed appliance, no-agent (cloud-PBX) |
| Build/release | CI matrix (GitHub Actions) builds + signs all OS/arch targets |
| Cloud ↔ agent | WebSocket (WSS) + REST |

---

## 9. Build Roadmap (Phased)

### Phase 1 — Prove the core
- Audio pipeline: weather → script → TTS → µ-law encode
- **Second content source: stocks** via `yfinance` (end-of-day summary) — proves the pluggable fetcher + prompt design with no new downstream work
- Multicast RTP sender; validate with **VLC** (`rtp://@<addr>:<port>`) and **Wireshark**
- Single-office test on real Yealink hardware
- *(Prototype can be Python; plan the production agent in Go from the start)*

### Phase 2 — Enterprise unlock
- SIP paging driver (works with any PBX) — biggest market expander
- **Build the production agent in Go**; ship the **native single-binary installer** (Windows + Linux x86-64 first) with auto-start service wrapper
- Stand up the **CI build/sign matrix**; add Docker image for technical customers
- Basic web dashboard: scheduling + content management

### Phase 3 — Hardening & scale
- Admin controls (quiet hours, priority, kill switch, approvals)
- Multi-site management + monitoring/heartbeat
- Security pass (TLS/SRTP, encrypted transport)
- Expand build matrix (Apple Silicon, ARM/Pi) as demand appears; offer **pre-flashed appliance** tier

### Phase 4 — Cloud-PBX integrations
- RingCentral, Zoom Phone, Teams, 8x8 API drivers (each opens a zero-on-prem market segment)

---

## 10. Local Test Environment (No Office Required)

You can develop and test the full stack on a laptop:

- **Audio pipeline** — run generation + encode, convert back to WAV, play locally.
- **Multicast RTP** — run sender + listen in **VLC** on the multicast address (loops back on one machine).
- **SIP path** — run **Asterisk in Docker** as a local PBX; register a **softphone** (Linphone / MicroSIP / Zoiper) as an extension; set up a paging group; have the app call into it.
- **Packet debugging** — **Wireshark** decodes RTP, shows header fields, and can replay the audio stream.

The code is identical between this test setup and a production office — only the "phone" changes (softphone app vs. physical desk phone).

---

## Appendix — Key Concepts Reference

- **PBX** — the call-control "brain"; routes calls, runs paging groups (FreePBX, Asterisk, Cisco UCM, cloud).
- **Provisioning server** — serves config files to phones at boot (often the same box as the PBX); found via DHCP Option 66.
- **SIP** — the text-based, HTTP-like protocol phones and the PBX use to set up/tear down calls (INVITE, REGISTER, ACK, BYE).
- **RTP** — carries the actual audio in 20 ms packets; flows directly between endpoints, bypassing the PBX.
- **Multicast paging** — one RTP stream to a multicast address; network fans it out to all subscribed phones. Preferred for scale and the simplest path for this product.
- **Paging extension** — a dialable number that broadcasts to a group of phones instead of ringing one person.
- **G.711 µ-law / A-law** — the universal 8 kHz phone codecs (µ-law in NA/Japan, A-law elsewhere).
