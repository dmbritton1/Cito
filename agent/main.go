package main

import (
	"encoding/base64"
	"encoding/json"
	"log"
	"os"
	"time"

	"github.com/gorilla/websocket"
)

type announceMsg struct {
	Type     string `json:"type"`
	Codec    string `json:"codec"`
	Addr     string `json:"addr"`
	Port     int    `json:"port"`
	AudioB64 string `json:"audio_b64"`
}

func getenv(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func main() {
	wsURL := getenv("CITO_CLOUD_WS", "ws://127.0.0.1:8000/agent")
	token := getenv("CITO_AGENT_TOKEN", "dev-token")
	var driver Driver = MulticastDriver{}
	for {
		if err := run(wsURL+"?token="+token, driver); err != nil {
			log.Printf("connection error: %v; retrying in 3s", err)
			time.Sleep(3 * time.Second)
		}
	}
}

func run(url string, driver Driver) error {
	conn, _, err := websocket.DefaultDialer.Dial(url, nil)
	if err != nil {
		return err
	}
	defer conn.Close()
	log.Println("connected to cloud")
	for {
		_, data, err := conn.ReadMessage()
		if err != nil {
			return err
		}
		var msg announceMsg
		if err := json.Unmarshal(data, &msg); err != nil {
			log.Printf("bad message: %v", err)
			continue
		}
		if msg.Type != "announce" {
			continue
		}
		mulaw, err := base64.StdEncoding.DecodeString(msg.AudioB64)
		if err != nil {
			log.Printf("bad audio: %v", err)
			continue
		}
		if err := driver.Deliver(mulaw, msg.Addr, msg.Port); err != nil {
			log.Printf("deliver error: %v", err)
			continue
		}
		log.Printf("received announce → sent %d packets", (len(mulaw)+payloadSize-1)/payloadSize)
	}
}
