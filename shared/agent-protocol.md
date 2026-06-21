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

## Heartbeat

The agent sends a heartbeat message every ~2 seconds to signal it is alive:

```json
{ "type": "heartbeat" }
```

The cloud considers the agent gone if it has not received a heartbeat (or any message)
within ~6 seconds and falls back to local multicast. This guards against the case where
the agent process has died but the WebSocket connection has not yet been closed at the
TCP/keepalive level.

Delivery (`announce`) is fire-and-forget: the cloud sends the announce message and does
not wait for any acknowledgement from the agent.
