package main

// Driver delivers finished µ-law audio to phones. Multicast now; SIP later (2c).
type Driver interface {
	Deliver(mulaw []byte, addr string, port int) error
}
