"""Pure RTP packetization for G.711 µ-law (PCMU) audio.

No sockets, no timing — just bytes, so it can be unit-tested offline.
160 bytes of µ-law = 20 ms of audio at 8 kHz.
"""

import struct

RTP_HEADER_SIZE = 12
RTP_PAYLOAD_SIZE = 160          # bytes of µ-law per packet (20 ms @ 8 kHz)
PAYLOAD_TYPE_PCMU = 0           # G.711 µ-law
TIMESTAMP_INCREMENT = 160       # samples per packet


def build_rtp_header(seq: int, timestamp: int, ssrc: int) -> bytes:
    """Build a 12-byte RTP header (V=2, P=0, X=0, CC=0, M=0, PT=0/PCMU)."""
    return struct.pack(
        "!BBHII",
        0x80,                       # V=2, P=0, X=0, CC=0
        PAYLOAD_TYPE_PCMU,          # M=0, PT=0 (PCMU)
        seq & 0xFFFF,
        timestamp & 0xFFFFFFFF,
        ssrc & 0xFFFFFFFF,
    )


def iter_rtp_packets(mulaw: bytes, ssrc: int, start_seq: int = 0, start_ts: int = 0):
    """Yield 172-byte RTP packets (12-byte header + up to 160-byte payload).

    The final packet may carry a shorter payload if the audio length is not a
    multiple of 160 bytes.
    """
    seq = start_seq
    timestamp = start_ts
    for offset in range(0, len(mulaw), RTP_PAYLOAD_SIZE):
        payload = mulaw[offset:offset + RTP_PAYLOAD_SIZE]
        yield build_rtp_header(seq, timestamp, ssrc) + payload
        seq = (seq + 1) & 0xFFFF
        timestamp = (timestamp + TIMESTAMP_INCREMENT) & 0xFFFFFFFF
