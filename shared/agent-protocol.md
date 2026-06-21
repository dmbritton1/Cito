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
