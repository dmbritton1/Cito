package main

import (
	"fmt"
	"math/rand"
	"net"
	"time"

	"golang.org/x/net/ipv4"
)

const packetInterval = 20 * time.Millisecond

// MulticastDriver streams RTP to a multicast group on a drift-corrected 20 ms cadence.
type MulticastDriver struct{}

func (MulticastDriver) Deliver(mulaw []byte, addr string, port int) error {
	group := net.ParseIP(addr)
	if group == nil {
		return fmt.Errorf("bad multicast address %q", addr)
	}
	iface, err := defaultInterface()
	if err != nil {
		return err
	}
	conn, err := net.ListenPacket("udp4", "0.0.0.0:0")
	if err != nil {
		return err
	}
	defer conn.Close()

	p := ipv4.NewPacketConn(conn)
	if err := p.SetMulticastInterface(iface); err != nil {
		return err
	}
	_ = p.SetMulticastLoopback(true) // so a local VLC on this machine hears it
	dst := &net.UDPAddr{IP: group, Port: port}

	packets := buildPackets(mulaw, rand.Uint32())
	start := time.Now()
	for i, pkt := range packets {
		if _, err := p.WriteTo(pkt, nil, dst); err != nil {
			return err
		}
		target := start.Add(time.Duration(i+1) * packetInterval)
		if d := time.Until(target); d > 0 {
			time.Sleep(d)
		}
	}
	return nil
}

// defaultInterface finds the interface on the default route (needed on macOS so multicast
// has an outgoing interface — the Go equivalent of the IP_MULTICAST_IF fix on the cloud).
func defaultInterface() (*net.Interface, error) {
	c, err := net.Dial("udp", "8.8.8.8:80") // no packets sent; just resolves the local IP
	if err != nil {
		return nil, err
	}
	defer c.Close()
	localIP := c.LocalAddr().(*net.UDPAddr).IP

	ifaces, err := net.Interfaces()
	if err != nil {
		return nil, err
	}
	for i := range ifaces {
		addrs, _ := ifaces[i].Addrs()
		for _, a := range addrs {
			if ipnet, ok := a.(*net.IPNet); ok && ipnet.IP.Equal(localIP) {
				return &ifaces[i], nil
			}
		}
	}
	return nil, fmt.Errorf("no interface found for local IP %v", localIP)
}
