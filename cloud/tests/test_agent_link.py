from cito import agent_link


def test_no_agent_deliver_returns_false(tmp_path):
    agent_link.unregister(None)  # ensure clean state
    f = tmp_path / "a.ulaw"
    f.write_bytes(b"\xff" * 320)
    assert agent_link.deliver(f, "224.0.1.75", 10000) is False
    assert agent_link.has_agent() is False


def test_deliver_sends_message_when_registered(monkeypatch, tmp_path):
    sent = {}

    class FakeWS:
        async def send_json(self, msg):
            sent["msg"] = msg
            agent_link.note_ack()  # simulate agent's immediate ack

    # Bridge: capture the coroutine and run it synchronously.
    def fake_threadsafe(coro, loop):
        import asyncio

        class FakeFuture:
            def result(self, timeout=None):
                return None

        ev = asyncio.new_event_loop()
        try:
            ev.run_until_complete(coro)
        finally:
            ev.close()
        return FakeFuture()

    monkeypatch.setattr("cito.agent_link.asyncio.run_coroutine_threadsafe", fake_threadsafe)
    agent_link.register(FakeWS(), object())
    f = tmp_path / "a.ulaw"
    f.write_bytes(b"\x10" * 160)
    assert agent_link.deliver(f, "224.0.1.75", 10000) is True
    assert sent["msg"]["type"] == "announce"
    assert sent["msg"]["addr"] == "224.0.1.75"
    assert "audio_b64" in sent["msg"]
    # clean up
    agent_link.unregister(None)
    agent_link._agent = None
    agent_link._ack.clear()


def test_deliver_falls_back_without_ack(monkeypatch, tmp_path):
    """When the agent never acks, deliver() must return False (fallback to multicast)."""

    class FakeWS:
        async def send_json(self, msg):
            pass  # intentionally does NOT call note_ack()

    def fake_threadsafe(coro, loop):
        import asyncio

        class FakeFuture:
            def result(self, timeout=None):
                return None

        ev = asyncio.new_event_loop()
        try:
            ev.run_until_complete(coro)
        finally:
            ev.close()
        return FakeFuture()

    monkeypatch.setattr("cito.agent_link.asyncio.run_coroutine_threadsafe", fake_threadsafe)
    monkeypatch.setattr("cito.agent_link.ACK_TIMEOUT", 0.05)  # fast timeout for test
    agent_link.register(FakeWS(), object())
    f = tmp_path / "a.ulaw"
    f.write_bytes(b"\x10" * 160)
    assert agent_link.deliver(f, "224.0.1.75", 10000) is False
    # clean up
    agent_link.unregister(None)
    agent_link._agent = None
    agent_link._ack.clear()
