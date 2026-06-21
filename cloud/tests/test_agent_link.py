import time

from cito import agent_link


def test_no_agent_deliver_returns_false(tmp_path):
    agent_link.unregister(None)  # ensure clean state
    f = tmp_path / "a.ulaw"
    f.write_bytes(b"\xff" * 320)
    assert agent_link.deliver(f, "224.0.1.75", 10000) is False
    assert agent_link.has_agent() is False


def test_deliver_true_when_recently_seen(monkeypatch, tmp_path):
    sent = {}

    class FakeWS:
        async def send_json(self, msg):
            sent["msg"] = msg

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
    agent_link.register(FakeWS(), object())  # sets _last_seen = now
    f = tmp_path / "a.ulaw"
    f.write_bytes(b"\x10" * 160)
    assert agent_link.deliver(f, "224.0.1.75", 10000) is True
    assert sent["msg"]["type"] == "announce"
    assert sent["msg"]["addr"] == "224.0.1.75"
    assert "audio_b64" in sent["msg"]
    # clean up
    agent_link._agent = None


def test_deliver_false_when_agent_stale(tmp_path):
    class FakeWS:
        async def send_json(self, msg):
            pass

    agent_link.register(FakeWS(), object())
    # Wind the clock back so the agent looks stale
    agent_link._last_seen = time.monotonic() - 100
    f = tmp_path / "a.ulaw"
    f.write_bytes(b"\x10" * 160)
    assert agent_link.deliver(f, "224.0.1.75", 10000) is False
    # clean up
    agent_link._agent = None
