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

## Delivery acknowledgement

After successfully delivering an announcement, the agent sends an ack back over the same
socket:

```json
{ "type": "ack", "packets": <int> }
```

where `packets` is the number of RTP packets transmitted. The cloud treats any
agent→cloud message as delivery confirmation. If no ack arrives within ~5 seconds of
sending the announcement, the cloud falls back to local multicast rather than silently
dropping the audio. This guards against the case where the agent process has died but the
WebSocket connection has not yet been closed at the TCP/keepalive level.
