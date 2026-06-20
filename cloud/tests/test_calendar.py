from datetime import date

import pytest

from cito.sources.calendar import CalendarSource

# Monday 2026-06-22. The weekly RRULE (anchored Mon 2026-06-15) recurs on it.
ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//test//EN
BEGIN:VEVENT
UID:1@test
SUMMARY:Client call
DTSTART:20260622T140000
DTEND:20260622T143000
END:VEVENT
BEGIN:VEVENT
UID:2@test
SUMMARY:Standup
DTSTART:20260615T090000
DTEND:20260615T091500
RRULE:FREQ=WEEKLY;BYDAY=MO
END:VEVENT
END:VCALENDAR
"""


class _FakeResp:
    text = ICS
    def raise_for_status(self):
        pass


def _pin_today(monkeypatch):
    class FakeDate(date):
        @classmethod
        def today(cls):
            return date(2026, 6, 22)
    monkeypatch.setattr("cito.sources.calendar.date", FakeDate)


def test_fetch_expands_recurrence_and_sorts(monkeypatch):
    _pin_today(monkeypatch)
    monkeypatch.setattr("cito.sources.calendar.httpx.get", lambda *a, **k: _FakeResp())
    monkeypatch.setattr("cito.sources.calendar.config.load_config",
                        lambda: {"calendar_url": "https://x/feed.ics"})
    events = CalendarSource().fetch()["events"]
    assert [e["summary"] for e in events] == ["Standup", "Client call"]
    assert events[0]["start"] == "9 AM"
    assert events[1]["start"] == "2 PM"


def test_fetch_without_url_raises(monkeypatch):
    monkeypatch.setattr("cito.sources.calendar.config.load_config",
                        lambda: {"calendar_url": ""})
    with pytest.raises(ValueError, match="calendar feed URL"):
        CalendarSource().fetch()


def test_prompt_fragment_lists_events():
    frag = CalendarSource().prompt_fragment(
        {"events": [{"summary": "Standup", "start": "9 AM", "all_day": False}]})
    assert "Today's schedule" in frag
    assert "9 AM Standup" in frag


def test_prompt_fragment_empty():
    frag = CalendarSource().prompt_fragment({"events": []})
    assert frag == "There are no events scheduled today."
