# Phase 2b — Go On-Prem Agent + Multicast Driver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Go on-prem agent that connects to the cloud over WSS, receives finished µ-law audio, and multicasts it to phones/VLC — with the cloud delivering to a connected agent and falling back to the existing in-process Python multicast when none is connected.

**Architecture:** A new Go module under `agent/` (WS client + RTP packetizer + multicast driver behind a `Driver` interface). The Python cloud adds a `/agent` WebSocket endpoint (token-authed), an `agent_link` module that pushes finished audio to the connected agent (bridging sync→async with `run_coroutine_threadsafe`), and a `send_announcement` hook that uses the agent when present, else the current local sender. Both sides log which path delivered.

**Tech Stack:** Go (gorilla/websocket, golang.org/x/net/ipv4), Python (FastAPI WebSocket — no new dep), pytest, ruff, `go test`. Run Python commands with `uv --directory cloud run ...` (do NOT `cd` into cloud). Run Go commands from `agent/`.

---

## File Structure

```
shared/agent-protocol.md      (new)  the cloud→agent message contract
agent/go.mod, go.sum          (new)  Go module + deps
agent/rtp.go                  (new)  RTP packetizer (port of cito/rtp.py)
agent/rtp_test.go             (new)  Go unit tests for the packetizer
agent/driver.go               (new)  Driver interface
agent/multicast.go            (new)  MulticastDriver (x/net/ipv4, drift-corrected pacing)
agent/main.go                 (new)  WS client: connect, receive, dispatch to driver
cloud/cito/agent_link.py      (new)  track connected agent + deliver(); sync→async bridge
cloud/cito/web/app.py         (mod)  WS /agent endpoint (token auth) + register/unregister
cloud/cito/pipeline.py        (mod)  send_announcement: agent-or-local-fallback + path logging
cloud/.env.example            (mod)  CITO_AGENT_TOKEN
cloud/tests/test_agent_link.py (new)
cloud/tests/test_web.py       (mod)  /agent WS auth
cloud/tests/test_pipeline.py  (mod)  send_announcement fallback/agent path
```

---

## Task 1: Prereqs — Go, module, deps, contract doc

**Files:**
- Create: `shared/agent-protocol.md`, `agent/go.mod`

- [ ] **Step 1: Install Go**

Run:
```bash
brew install go
go version
```
Expected: a `go version go1.2x …` line.

- [ ] **Step 2: Initialize the Go module and add deps**

Run (from repo root):
```bash
cd /Users/dwightbritton/Desktop/Cito/agent && go mod init cito/agent && \
  go get github.com/gorilla/websocket && go get golang.org/x/net/ipv4
```
Expected: creates `agent/go.mod` + `agent/go.sum` with both deps.
(If a sandbox blocks `cd`, run `go mod init` etc. with `-C /Users/dwightbritton/Desktop/Cito/agent`.)

- [ ] **Step 3: Write the contract doc**

Create `shared/agent-protocol.md`:
```markdown
# Cloud ↔ Agent Protocol (Phase 2b)

The agent connects to the cloud as a WebSocket client:

    wss://<cloud-host>/agent?token=<CITO_AGENT_TOKEN>

A missing/incorrect token is rejected with close code 1008.

The cloud pushes one JSON message per announcement:

```json
{
  "type": "announce",
  "codec": "pcmu",
  "addr": "224.0.1.75",
  "port": 10000,
  "audio_b64": "<base64 of the raw headerless G.711 µ-law bytes>"
}
```

The agent base64-decodes `audio_b64` and delivers it via the driver named by `codec`
(currently always the multicast RTP driver) to `addr:port`. Audio is embedded (files are
tens of KB). REST fallback, SIP, and agent→cloud status are later phases.
```

- [ ] **Step 4: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add agent/go.mod agent/go.sum shared/agent-protocol.md
git commit -m "Init Go agent module and cloud-agent protocol doc"
```

---

## Task 2: Go RTP packetizer (TDD)

**Files:**
- Create: `agent/rtp.go`, `agent/rtp_test.go`

- [ ] **Step 1: Write the failing test**

Create `agent/rtp_test.go`:
```go
package main

import (
	"encoding/binary"
	"testing"
)

func TestFullPacketHeaderAndSize(t *testing.T) {
	p := buildPackets(make([]byte, payloadSize), 0x11223344)
	if p[0][0] != 0x80 {
		t.Fatalf("byte0 = %#x, want 0x80", p[0][0])
	}
	if p[0][1] != 0x00 {
		t.Fatalf("byte1 = %#x, want 0x00", p[0][1])
	}
	if len(p[0]) != 172 {
		t.Fatalf("len = %d, want 172", len(p[0]))
	}
}

func TestSeqAndTimestampIncrement(t *testing.T) {
	p := buildPackets(make([]byte, payloadSize*3), 0)
	for i := 0; i < 3; i++ {
		if seq := binary.BigEndian.Uint16(p[i][2:4]); int(seq) != i {
			t.Fatalf("seq[%d] = %d", i, seq)
		}
		if ts := binary.BigEndian.Uint32(p[i][4:8]); int(ts) != i*160 {
			t.Fatalf("ts[%d] = %d", i, ts)
		}
	}
}

func TestShortFinalPayload(t *testing.T) {
	p := buildPackets(make([]byte, payloadSize+80), 0)
	if len(p) != 2 {
		t.Fatalf("packets = %d, want 2", len(p))
	}
	if len(p[1]) != headerSize+80 {
		t.Fatalf("last len = %d, want %d", len(p[1]), headerSize+80)
	}
}
```

- [ ] **Step 2: Run to verify it fails**

Run (from `agent/`):
```bash
go test ./...
```
Expected: FAIL — `undefined: buildPackets` / `undefined: payloadSize`.

- [ ] **Step 3: Implement**

Create `agent/rtp.go`:
```go
package main

import "encoding/binary"

const (
	payloadSize = 160 // bytes of µ-law per packet (20 ms @ 8 kHz)
	headerSize  = 12
)

// buildPackets slices mulaw into RTP packets (12-byte header + up to 160-byte payload).
func buildPackets(mulaw []byte, ssrc uint32) [][]byte {
	var packets [][]byte
	var seq uint16
	var ts uint32
	for off := 0; off < len(mulaw); off += payloadSize {
		end := off + payloadSize
		if end > len(mulaw) {
			end = len(mulaw)
		}
		pkt := make([]byte, headerSize, headerSize+(end-off))
		pkt[0] = 0x80 // V=2, P=0, X=0, CC=0
		pkt[1] = 0x00 // M=0, PT=0 (PCMU)
		binary.BigEndian.PutUint16(pkt[2:4], seq)
		binary.BigEndian.PutUint32(pkt[4:8], ts)
		binary.BigEndian.PutUint32(pkt[8:12], ssrc)
		pkt = append(pkt, mulaw[off:end]...)
		packets = append(packets, pkt)
		seq++
		ts += payloadSize
	}
	return packets
}
```

- [ ] **Step 4: Run to verify it passes**

Run (from `agent/`):
```bash
go test ./...
```
Expected: `ok  cito/agent` (3 tests pass).

- [ ] **Step 5: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add agent/rtp.go agent/rtp_test.go
git commit -m "Add Go RTP packetizer with unit tests"
```

---

## Task 3: Go driver + multicast + WS client

**Files:**
- Create: `agent/driver.go`, `agent/multicast.go`, `agent/main.go`

- [ ] **Step 1: Driver interface**

Create `agent/driver.go`:
```go
package main

// Driver delivers finished µ-law audio to phones. Multicast now; SIP later (2c).
type Driver interface {
	Deliver(mulaw []byte, addr string, port int) error
}
```

- [ ] **Step 2: Multicast driver**

Create `agent/multicast.go`:
```go
package main

import (
	"fmt"
	"math/rand"
	"net"
	"time"

	"golang.org/x/net/ipv4"
)

const packetInterval = 20 * time.Millisecond

// MulticastDriver streams RTP to a multicast group on a drift-corrected 20 ms cadence.
type MulticastDriver struct{}

func (MulticastDriver) Deliver(mulaw []byte, addr string, port int) error {
	group := net.ParseIP(addr)
	if group == nil {
		return fmt.Errorf("bad multicast address %q", addr)
	}
	iface, err := defaultInterface()
	if err != nil {
		return err
	}
	conn, err := net.ListenPacket("udp4", "0.0.0.0:0")
	if err != nil {
		return err
	}
	defer conn.Close()

	p := ipv4.NewPacketConn(conn)
	if err := p.SetMulticastInterface(iface); err != nil {
		return err
	}
	_ = p.SetMulticastLoopback(true) // so a local VLC on this machine hears it
	dst := &net.UDPAddr{IP: group, Port: port}

	packets := buildPackets(mulaw, rand.Uint32())
	start := time.Now()
	for i, pkt := range packets {
		if _, err := p.WriteTo(pkt, nil, dst); err != nil {
			return err
		}
		target := start.Add(time.Duration(i+1) * packetInterval)
		if d := time.Until(target); d > 0 {
			time.Sleep(d)
		}
	}
	return nil
}

// defaultInterface finds the interface on the default route (needed on macOS so multicast
// has an outgoing interface — the Go equivalent of the IP_MULTICAST_IF fix on the cloud).
func defaultInterface() (*net.Interface, error) {
	c, err := net.Dial("udp", "8.8.8.8:80") // no packets sent; just resolves the local IP
	if err != nil {
		return nil, err
	}
	defer c.Close()
	localIP := c.LocalAddr().(*net.UDPAddr).IP

	ifaces, err := net.Interfaces()
	if err != nil {
		return nil, err
	}
	for i := range ifaces {
		addrs, _ := ifaces[i].Addrs()
		for _, a := range addrs {
			if ipnet, ok := a.(*net.IPNet); ok && ipnet.IP.Equal(localIP) {
				return &ifaces[i], nil
			}
		}
	}
	return nil, fmt.Errorf("no interface found for local IP %v", localIP)
}
```

- [ ] **Step 3: WS client main**

Create `agent/main.go`:
```go
package main

import (
	"encoding/base64"
	"encoding/json"
	"log"
	"os"
	"time"

	"github.com/gorilla/websocket"
)

type announceMsg struct {
	Type     string `json:"type"`
	Codec    string `json:"codec"`
	Addr     string `json:"addr"`
	Port     int    `json:"port"`
	AudioB64 string `json:"audio_b64"`
}

func getenv(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func main() {
	wsURL := getenv("CITO_CLOUD_WS", "ws://127.0.0.1:8000/agent")
	token := getenv("CITO_AGENT_TOKEN", "dev-token")
	var driver Driver = MulticastDriver{}
	for {
		if err := run(wsURL+"?token="+token, driver); err != nil {
			log.Printf("connection error: %v; retrying in 3s", err)
			time.Sleep(3 * time.Second)
		}
	}
}

func run(url string, driver Driver) error {
	conn, _, err := websocket.DefaultDialer.Dial(url, nil)
	if err != nil {
		return err
	}
	defer conn.Close()
	log.Println("connected to cloud")
	for {
		_, data, err := conn.ReadMessage()
		if err != nil {
			return err
		}
		var msg announceMsg
		if err := json.Unmarshal(data, &msg); err != nil {
			log.Printf("bad message: %v", err)
			continue
		}
		if msg.Type != "announce" {
			continue
		}
		mulaw, err := base64.StdEncoding.DecodeString(msg.AudioB64)
		if err != nil {
			log.Printf("bad audio: %v", err)
			continue
		}
		if err := driver.Deliver(mulaw, msg.Addr, msg.Port); err != nil {
			log.Printf("deliver error: %v", err)
			continue
		}
		log.Printf("received announce → sent %d packets", (len(mulaw)+payloadSize-1)/payloadSize)
	}
}
```

- [ ] **Step 4: Build + vet**

Run (from `agent/`):
```bash
go build ./... && go vet ./... && go test ./...
```
Expected: builds cleanly, vet silent, tests pass. (No socket unit test here; the multicast/WS paths are exercised in the manual e2e in Task 6.)

- [ ] **Step 5: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add agent/driver.go agent/multicast.go agent/main.go agent/go.mod agent/go.sum
git commit -m "Add Go agent: driver interface, multicast driver, WS client"
```

---

## Task 4: Cloud agent_link + WS endpoint (TDD)

**Files:**
- Create: `cloud/cito/agent_link.py`
- Modify: `cloud/cito/web/app.py`, `cloud/.env.example`
- Test: `cloud/tests/test_agent_link.py`, `cloud/tests/test_web.py`

- [ ] **Step 1: Write the failing tests**

Create `cloud/tests/test_agent_link.py`:
```python
from cito import agent_link


def test_no_agent_deliver_returns_false(tmp_path):
    agent_link.unregister(None)  # ensure clean state
    f = tmp_path / "a.ulaw"
    f.write_bytes(b"\xff" * 320)
    assert agent_link.deliver(f, "224.0.1.75", 10000) is False
    assert agent_link.has_agent() is False


def test_deliver_sends_message_when_registered(monkeypatch, tmp_path):
    sent = {}

    class FakeWS:
        async def send_json(self, msg):
            sent["msg"] = msg

    class FakeFuture:
        def result(self, timeout=None):
            return None

    # Bridge: capture the coroutine and run it, return a fake future.
    def fake_threadsafe(coro, loop):
        import asyncio
        asyncio.new_event_loop().run_until_complete(coro)
        return FakeFuture()

    monkeypatch.setattr("cito.agent_link.asyncio.run_coroutine_threadsafe", fake_threadsafe)
    agent_link.register(FakeWS(), object())
    f = tmp_path / "a.ulaw"
    f.write_bytes(b"\x10" * 160)
    assert agent_link.deliver(f, "224.0.1.75", 10000) is True
    assert sent["msg"]["type"] == "announce"
    assert sent["msg"]["addr"] == "224.0.1.75"
    assert "audio_b64" in sent["msg"]
    agent_link.unregister(None)
    agent_link._agent = None  # full reset for other tests
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv --directory cloud run pytest tests/test_agent_link.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cito.agent_link'`.

- [ ] **Step 3: Implement agent_link**

Create `cloud/cito/agent_link.py`:
```python
"""Track the connected on-prem agent and push finished audio to it over WSS.

`deliver` is called from sync code (scheduler thread, request handlers) but the agent
socket lives on the asyncio loop, so we bridge with run_coroutine_threadsafe.
"""

import asyncio
import base64
import logging
from pathlib import Path

logger = logging.getLogger("cito.agent_link")

_agent = None  # the connected WebSocket (single agent for now)
_loop = None   # the asyncio loop the socket lives on


def register(ws, loop) -> None:
    global _agent, _loop
    _agent, _loop = ws, loop
    logger.info("agent connected")


def unregister(ws) -> None:
    """Clear the agent if `ws` is the current one (or always, when passed None)."""
    global _agent, _loop
    if ws is None or _agent is ws:
        _agent, _loop = None, None
        logger.info("agent disconnected")


def has_agent() -> bool:
    return _agent is not None


def deliver(ulaw_path, addr: str, port: int) -> bool:
    """Push finished µ-law audio to the connected agent. True if delivered, else False."""
    if _agent is None or _loop is None:
        return False
    audio_b64 = base64.b64encode(Path(ulaw_path).read_bytes()).decode("ascii")
    msg = {"type": "announce", "codec": "pcmu", "addr": addr, "port": port,
           "audio_b64": audio_b64}
    try:
        future = asyncio.run_coroutine_threadsafe(_agent.send_json(msg), _loop)
        future.result(timeout=10)
        return True
    except Exception:
        logger.warning("agent delivery failed; will fall back")
        return False
```

- [ ] **Step 4: Add the WS endpoint + token**

In `cloud/cito/web/app.py`:

(a) Add imports — extend the fastapi import and add asyncio/os + agent_link:
```python
import asyncio
import os
from fastapi import FastAPI, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
```
and add `agent_link` to the cito import line (e.g. `from cito import agent_link, announcements, config, documents, pipeline, scheduler`).

(b) After the `app = FastAPI(...)` line, add the token constant:
```python
AGENT_TOKEN = os.environ.get("CITO_AGENT_TOKEN", "dev-token")
```

(c) Add the WebSocket endpoint (after the `/announcements-ui` route):
```python
@app.websocket("/agent")
async def agent_ws(ws: WebSocket) -> None:
    if ws.query_params.get("token") != AGENT_TOKEN:
        await ws.close(code=1008)
        return
    await ws.accept()
    agent_link.register(ws, asyncio.get_running_loop())
    try:
        while True:
            await ws.receive_text()  # drain keepalives; block until disconnect
    except WebSocketDisconnect:
        pass
    finally:
        agent_link.unregister(ws)
```

- [ ] **Step 5: Add the token to .env.example**

In `cloud/.env.example`, add a line:
```
CITO_AGENT_TOKEN=dev-token
```

- [ ] **Step 6: Write + run the WS auth test**

Append to `cloud/tests/test_web.py`:
```python
def test_agent_ws_accepts_valid_token(monkeypatch):
    from fastapi.testclient import TestClient
    from cito.web import app as webapp
    monkeypatch.setattr("cito.web.app.AGENT_TOKEN", "test-token")
    client = TestClient(webapp.app)
    with client.websocket_connect("/agent?token=test-token") as ws:
        assert ws is not None  # handshake accepted


def test_agent_ws_rejects_bad_token(monkeypatch):
    import pytest
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    from cito.web import app as webapp
    monkeypatch.setattr("cito.web.app.AGENT_TOKEN", "test-token")
    client = TestClient(webapp.app)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/agent?token=wrong"):
            pass
```

Run: `uv --directory cloud run pytest tests/test_agent_link.py tests/test_web.py -v`
Expected: all PASS. Then `uv --directory cloud run ruff check .` → clean.

- [ ] **Step 7: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add cloud/cito/agent_link.py cloud/cito/web/app.py cloud/.env.example \
        cloud/tests/test_agent_link.py cloud/tests/test_web.py
git commit -m "Add cloud agent link + token-authed /agent WebSocket"
```

---

## Task 5: Pipeline delivery — agent-or-fallback (TDD)

**Files:**
- Modify: `cloud/cito/pipeline.py`
- Test: `cloud/tests/test_pipeline.py`

- [ ] **Step 1: Write the failing tests**

Append to `cloud/tests/test_pipeline.py`:
```python
def test_send_uses_agent_when_connected(monkeypatch, tmp_path):
    from cito import pipeline
    ulaw = tmp_path / "out.ulaw"
    ulaw.write_bytes(b"\xff" * 320)  # 2 packets
    monkeypatch.setattr("cito.pipeline.tts.synthesize", lambda text: "out.mp3")
    monkeypatch.setattr("cito.pipeline.audio.encode_mulaw", lambda mp3: ulaw)
    monkeypatch.setattr("cito.pipeline.agent_link.deliver", lambda p, a, port: True)
    sent_local = {"called": False}
    monkeypatch.setattr("cito.pipeline.MulticastRTPSender",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not send locally")))
    result = pipeline.send_announcement("hello")
    assert result.packets == 2  # computed from the µ-law length, not the local sender


def test_send_falls_back_to_local_without_agent(monkeypatch, tmp_path):
    from cito import pipeline
    ulaw = tmp_path / "out.ulaw"
    ulaw.write_bytes(b"\xff" * 160)
    monkeypatch.setattr("cito.pipeline.tts.synthesize", lambda text: "out.mp3")
    monkeypatch.setattr("cito.pipeline.audio.encode_mulaw", lambda mp3: ulaw)
    monkeypatch.setattr("cito.pipeline.agent_link.deliver", lambda p, a, port: False)

    class FakeSender:
        def send(self, path):
            return 7

    monkeypatch.setattr("cito.pipeline.MulticastRTPSender", lambda *a, **k: FakeSender())
    result = pipeline.send_announcement("hello")
    assert result.packets == 7  # local sender's count
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv --directory cloud run pytest tests/test_pipeline.py -k send_ -v`
Expected: FAIL (`send_announcement` doesn't reference `agent_link`).

- [ ] **Step 3: Implement**

In `cloud/cito/pipeline.py`:

(a) Add a logger + the agent_link import + delivery constants near the top (after the existing imports):
```python
import logging

from cito import agent_link, audio, config, documents, tts

logger = logging.getLogger("cito.pipeline")
DELIVERY_ADDR = "224.0.1.75"
DELIVERY_PORT = 10000
```
(Replace the existing `from cito import audio, config, documents, tts` line with the one above that adds `agent_link`.)

(b) Replace `send_announcement` with:
```python
def send_announcement(text: str) -> SendResult:
    """Speak `text`: TTS -> µ-law -> deliver via the agent if connected, else locally."""
    if not text or not text.strip():
        raise ValueError("cannot send an empty announcement")
    mp3 = tts.synthesize(text.strip())
    ulaw = Path(audio.encode_mulaw(Path(mp3)))
    if agent_link.deliver(ulaw, DELIVERY_ADDR, DELIVERY_PORT):
        packets = (ulaw.stat().st_size + 159) // 160
        logger.info("delivered via agent (%d packets)", packets)
        return SendResult(packets=packets)
    logger.info("no agent — local fallback")
    packets = MulticastRTPSender(DELIVERY_ADDR, DELIVERY_PORT).send(ulaw)
    return SendResult(packets=packets)
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv --directory cloud run pytest tests/test_pipeline.py -v`
Expected: all PASS (existing + 2 new). Then `uv --directory cloud run ruff check .` → clean and `uv --directory cloud run pytest -q` fully green.

- [ ] **Step 5: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add cloud/cito/pipeline.py cloud/tests/test_pipeline.py
git commit -m "Deliver via agent when connected, else local fallback"
```

---

## Task 6: README + live end-to-end verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the README**

In `README.md`, after the scheduler paragraph (before `## Status`), add:
```markdown
**On-prem agent (Phase 2b):** the cloud can deliver through a small Go agent instead of
sending RTP itself. Build/run it from `agent/`: `go run .` (it reads `CITO_CLOUD_WS`,
default `ws://127.0.0.1:8000/agent`, and `CITO_AGENT_TOKEN`, default `dev-token`). With the
agent connected, the cloud ships finished audio to it over WSS and the agent does the
multicast; with no agent connected, the cloud falls back to its own in-process multicast.
The cloud log shows which path delivered (`delivered via agent` vs `no agent — local
fallback`).
```

- [ ] **Step 2: Live end-to-end (manual, by ear)**

Three terminals + VLC:
```bash
# Terminal A — cloud (no --reload)
uv --directory cloud run uvicorn cito.web.app:app --port 8000
# Terminal B — agent
cd /Users/dwightbritton/Desktop/Cito/agent && CITO_AGENT_TOKEN=dev-token go run .
```
VLC: Open RTP/UDP Stream → RTP, Multicast, `224.0.1.75`, `10000`.
Then in a browser at `http://127.0.0.1:8000` fire an announcement (Send, or Run-now from the
announcements page). Confirm:
- Terminal B (agent) prints `connected to cloud` then `received announce → sent N packets`.
- Terminal A (cloud) logs `delivered via agent`.
- VLC plays the audio.
Now **stop the agent** (Ctrl-C in Terminal B), fire again, and confirm Terminal A logs
`no agent — local fallback` and VLC still plays. (Both paths proven.)

- [ ] **Step 3: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add README.md
git commit -m "Document the Go on-prem agent and how to run it"
```

---

## Exit Criteria (verify all)

- [ ] `go test ./...` (in `agent/`) and `uv --directory cloud run pytest -q` both green; `ruff check .` clean; `go vet ./...` clean.
- [ ] With the Go agent connected, a fired announcement is delivered via the agent (agent logs `sent N packets`, cloud logs `delivered via agent`) and plays in VLC.
- [ ] With no agent connected, the cloud logs `local fallback` and still plays via the in-process sender.
- [ ] A bad token is rejected at the WS handshake (close 1008).
- [ ] The cloud Python suite is unchanged in behavior when no agent is connected (existing flows intact).
