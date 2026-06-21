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
