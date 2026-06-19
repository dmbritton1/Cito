"""Stream a raw µ-law file as RTP multicast (the Phase 0 spike).

Usage:  uv run python -m cito.spikes.rtp_send test.ulaw
"""

import argparse
import random
import socket
import time

from cito.rtp import iter_rtp_packets

DEFAULT_ADDR = "224.0.1.75"
DEFAULT_PORT = 10000
PACKET_INTERVAL_S = 0.02          # 20 ms cadence
MULTICAST_TTL = 1


def _outgoing_ip() -> str:
    """Best-effort local IP of the default-route interface.

    Multicast sends need an explicit outgoing interface on macOS, otherwise
    sendto() raises "No route to host". No packets are sent by this probe.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    finally:
        probe.close()


def send(path: str, addr: str = DEFAULT_ADDR, port: int = DEFAULT_PORT) -> int:
    with open(path, "rb") as f:
        mulaw = f.read()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, MULTICAST_TTL)
    # Send out the default-route interface and loop back so a local listener
    # (e.g. VLC on this machine) receives the stream.
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(_outgoing_ip()))
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)

    ssrc = random.getrandbits(32)
    count = 0
    try:
        for packet in iter_rtp_packets(mulaw, ssrc=ssrc):
            sock.sendto(packet, (addr, port))
            count += 1
            time.sleep(PACKET_INTERVAL_S)
    finally:
        sock.close()
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Stream a µ-law file as RTP multicast.")
    parser.add_argument("file", help="raw headerless µ-law file (e.g. test.ulaw)")
    parser.add_argument("--addr", default=DEFAULT_ADDR)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    count = send(args.file, args.addr, args.port)
    print(f"Sent {count} packets to {args.addr}:{args.port}")


if __name__ == "__main__":
    main()
