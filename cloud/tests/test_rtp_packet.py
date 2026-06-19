import struct

from cito.rtp import build_rtp_header, iter_rtp_packets, RTP_PAYLOAD_SIZE


def test_header_first_byte_is_0x80():
    # Version 2, no padding/extension/CSRC -> 0x80
    assert build_rtp_header(seq=0, timestamp=0, ssrc=0x11223344)[0] == 0x80


def test_header_payload_type_is_pcmu():
    # Marker 0, payload type 0 (PCMU/G.711 µ-law) -> 0x00
    assert build_rtp_header(seq=0, timestamp=0, ssrc=0)[1] == 0x00


def test_header_is_12_bytes():
    assert len(build_rtp_header(seq=1, timestamp=160, ssrc=0)) == 12


def test_sequence_increments_by_one():
    data = b"\xff" * (RTP_PAYLOAD_SIZE * 3)
    packets = list(iter_rtp_packets(data, ssrc=0x11223344))
    seqs = [struct.unpack("!H", p[2:4])[0] for p in packets]
    assert seqs == [0, 1, 2]


def test_timestamp_increments_by_160():
    data = b"\xff" * (RTP_PAYLOAD_SIZE * 3)
    packets = list(iter_rtp_packets(data, ssrc=0))
    timestamps = [struct.unpack("!I", p[4:8])[0] for p in packets]
    assert timestamps == [0, 160, 320]


def test_full_packet_is_172_bytes():
    data = b"\xff" * RTP_PAYLOAD_SIZE
    packets = list(iter_rtp_packets(data, ssrc=0))
    assert len(packets[0]) == 172


def test_short_final_payload_is_preserved():
    data = b"\xff" * (RTP_PAYLOAD_SIZE + 80)
    packets = list(iter_rtp_packets(data, ssrc=0))
    assert len(packets) == 2
    assert len(packets[1]) == 12 + 80
