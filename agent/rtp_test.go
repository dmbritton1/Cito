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
