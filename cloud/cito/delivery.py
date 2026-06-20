"""Multicast RTP delivery — a clean class promoting the Phase 0 spike.

Reuses cito.rtp.iter_rtp_packets. Sets the macOS outgoing interface + loopback so a
local VLC listener receives the stream.
"""

import random
import socket
import time
from pathlib import Path

from cito.rtp import iter_rtp_packets

PACKET_INTERVAL_S = 0.02
MULTICAST_TTL = 1

# Per-brand defaults — other brands become entries here, not code branches.
BRAND_PORTS = {"yealink": 10000}


def _outgoing_ip() -> str:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    finally:
        probe.close()


class MulticastRTPSender:
    def __init__(self, addr: str = "224.0.1.75", port: int = 10000):
        self.addr = addr
        self.port = port

    def send(self, ulaw_file: Path) -> int:
        with open(ulaw_file, "rb") as f:
            mulaw = f.read()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, MULTICAST_TTL)
        sock.setsockopt(
            socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(_outgoing_ip())
        )
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
        count = 0
        # Drift-corrected pacing: each packet has an absolute deadline (start + n*20ms),
        # so we sleep only the time still remaining. A plain sleep(0.02) overshoots and
        # the error accumulates, delivering the stream slower than real-time and starving
        # the receiver's jitter buffer (audible cuts).
        start = time.perf_counter()
        try:
            for i, packet in enumerate(iter_rtp_packets(mulaw, ssrc=random.getrandbits(32))):
                sock.sendto(packet, (self.addr, self.port))
                count += 1
                remaining = start + (i + 1) * PACKET_INTERVAL_S - time.perf_counter()
                if remaining > 0:
                    time.sleep(remaining)
        finally:
            sock.close()
        return count
