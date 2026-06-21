from cito import scheduler

REC_SOURCES = {"id": "a1", "name": "Brief", "kind": "sources",
               "sources": ["weather"], "message": "", "time": "08:30", "days": ["mon", "fri"]}
REC_MESSAGE = {"id": "b2", "name": "Standup", "kind": "message",
               "sources": [], "message": "Standup now.", "time": "09:55", "days": ["mon"]}


def test_trigger_maps_time_and_days():
    t = str(scheduler._trigger(REC_SOURCES))
    assert "day_of_week='mon,fri'" in t
    assert "hour='8'" in t
    assert "minute='30'" in t


def test_run_announcement_sources(monkeypatch):
    calls = {}

    def fake_generate(sources):
        calls["gen"] = sources
        return "GENERATED"

    monkeypatch.setattr("cito.scheduler.pipeline.generate_announcement", fake_generate)
    monkeypatch.setattr("cito.scheduler.pipeline.send_announcement",
                        lambda text: calls.setdefault("sent", text))
    out = scheduler.run_announcement(REC_SOURCES)
    assert calls["gen"] == ["weather"]
    assert calls["sent"] == "GENERATED"
    assert out == "GENERATED"


def test_run_announcement_message(monkeypatch):
    sent = {}
    monkeypatch.setattr("cito.scheduler.pipeline.send_announcement",
                        lambda text: sent.setdefault("text", text))
    out = scheduler.run_announcement(REC_MESSAGE)
    assert sent["text"] == "Standup now."
    assert out == "Standup now."


def test_reschedule_and_unschedule_register_a_job():
    scheduler.reschedule(REC_SOURCES)
    assert scheduler._scheduler.get_job("a1") is not None
    scheduler.unschedule("a1")
    assert scheduler._scheduler.get_job("a1") is None
