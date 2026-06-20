"""Calendar source — today's events from an iCal/.ics feed, with recurrence expansion.

Structured data queried by date (spec 3.6), a sibling to weather/stocks — NOT RAG.
"""

from datetime import date, datetime, time, timedelta  # noqa: F401  (date kept for test monkeypatching seam)

import httpx
import icalendar
import recurring_ical_events

from cito import config


def _local_tz():
    """The machine's local timezone (monkeypatchable in tests)."""
    return datetime.now().astimezone().tzinfo


def _now_local() -> datetime:
    """Current local datetime (monkeypatchable in tests)."""
    return datetime.now(_local_tz())


def _fmt_time(dt: datetime) -> str:
    """Spoken-friendly clock time in local tz, e.g. '9 AM', '2:30 PM'."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(_local_tz())
    hour = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"
    return f"{hour}:{dt.minute:02d} {ampm}" if dt.minute else f"{hour} {ampm}"


def _minutes(dtstart) -> int:
    """Sort key: all-day events (a date, not datetime) sort first."""
    return dtstart.hour * 60 + dtstart.minute if isinstance(dtstart, datetime) else -1


class CalendarSource:
    name = "calendar"

    def fetch(self) -> dict:
        url = (config.load_config().get("calendar_url") or "").strip()
        if not url:
            raise ValueError("no calendar feed URL configured")
        resp = httpx.get(url, timeout=15.0)
        resp.raise_for_status()
        cal = icalendar.Calendar.from_ical(resp.text)

        today = _now_local().date()
        start = datetime.combine(today, time.min, tzinfo=_local_tz())
        end = start + timedelta(days=1)
        occurrences = recurring_ical_events.of(cal).between(start, end)

        events = []
        for ev in occurrences:
            dtstart = ev.get("DTSTART").dt
            all_day = not isinstance(dtstart, datetime)
            # Convert tz-aware datetimes to local once so display and sort agree
            if isinstance(dtstart, datetime) and dtstart.tzinfo is not None:
                dtstart = dtstart.astimezone(_local_tz())
            events.append({
                "summary": str(ev.get("SUMMARY", "")).strip(),
                "start": "all day" if all_day else _fmt_time(dtstart),
                "all_day": all_day,
                "_m": _minutes(dtstart),
            })
        events.sort(key=lambda e: e["_m"])
        for e in events:
            del e["_m"]
        return {"events": events}

    def prompt_fragment(self, data: dict) -> str:
        events = data.get("events", [])
        if not events:
            return "There are no events scheduled today."
        parts = [
            f"{e['summary']} (all day)" if e["all_day"] else f"{e['start']} {e['summary']}"
            for e in events
        ]
        return "Today's schedule: " + "; ".join(parts) + "."
