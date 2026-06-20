from datetime import datetime, timedelta, timezone

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

ICS_UTC = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//test//EN
BEGIN:VEVENT
UID:3@test
SUMMARY:UTC event
DTSTART:20260622T140000Z
DTEND:20260622T150000Z
END:VEVENT
END:VCALENDAR
"""


class _FakeResp:
    text = ICS
    def raise_for_status(self):
        pass


class _FakeRespUTC:
    text = ICS_UTC
    def raise_for_status(self):
        pass


def _pin_today(monkeypatch, tz=timezone.utc):
    """Pin _local_tz and _now_local so fetch() uses 2026-06-22 in UTC."""
    monkeypatch.setattr("cito.sources.calendar._local_tz", lambda: tz)
    fixed = datetime(2026, 6, 22, 12, 0, tzinfo=tz)
    monkeypatch.setattr("cito.sources.calendar._now_local", lambda: fixed)


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


def test_fetch_utc_event_converted_to_local(monkeypatch):
    """A UTC DTSTART (14:00Z) must display as 9 AM in US/Eastern (UTC-5, no DST)."""
    eastern = timezone(timedelta(hours=-5))
    _pin_today(monkeypatch, tz=eastern)
    monkeypatch.setattr("cito.sources.calendar.httpx.get", lambda *a, **k: _FakeRespUTC())
    monkeypatch.setattr("cito.sources.calendar.config.load_config",
                        lambda: {"calendar_url": "https://x/feed.ics"})
    events = CalendarSource().fetch()["events"]
    assert len(events) == 1
    assert events[0]["summary"] == "UTC event"
    assert events[0]["start"] == "9 AM"
