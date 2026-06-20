# Phase 3c — Calendar Source (as content) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a calendar content source that reads today's events (with recurrence) from an iCal/`.ics` feed and announces them, combining with the existing sources.

**Architecture:** A new `CalendarSource` implements the existing `Source` protocol and registers in `SOURCES`, so it flows through the toggle/combine pipeline with no engine changes. The feed URL lives in the persisted config (which is upgraded to merge-on-save so calendar and voice settings coexist). Recurrence is expanded with `icalendar` + `recurring-ical-events`.

**Tech Stack:** Python 3.11+ (uv), icalendar, recurring-ical-events, httpx, FastAPI, pytest, ruff. Run commands with `uv --directory cloud run ...` (do NOT `cd` into cloud).

---

## File Structure

```
cloud/cito/config.py          (mod)  + calendar_url; save_config merges (no clobber)
cloud/cito/sources/calendar.py (new) CalendarSource: fetch() today's events + prompt_fragment
cloud/cito/sources/__init__.py (mod) register "calendar"
cloud/cito/web/app.py         (mod)  GET /config returns calendar_url; POST /calendar saves it
cloud/cito/web/index.html     (mod)  Calendar checkbox + feed-URL field/Save
cloud/pyproject.toml          (mod)  + icalendar, recurring-ical-events
cloud/tests/test_config.py    (mod)  calendar_url round-trip + merge
cloud/tests/test_calendar.py  (new)
cloud/tests/test_web.py       (mod)  /calendar + /config calendar_url
```

---

## Task 1: Add dependencies

**Files:**
- Modify: `cloud/pyproject.toml`

- [ ] **Step 1: Add the two parsing deps**

In `cloud/pyproject.toml`, append `icalendar` and `recurring-ical-events` to `[project].dependencies` so the list ends:
```toml
    "python-docx",
    "pypdf",
    "python-multipart",
    "icalendar",
    "recurring-ical-events",
]
```

- [ ] **Step 2: Sync and verify imports**

Run:
```bash
uv --directory cloud sync
uv --directory cloud run python -c "import icalendar, recurring_ical_events; print('ok')"
```
Expected: `ok` (the import name for recurring-ical-events is `recurring_ical_events`).

- [ ] **Step 3: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add cloud/pyproject.toml cloud/uv.lock
git commit -m "Add calendar deps: icalendar, recurring-ical-events"
```

---

## Task 2: Config — calendar_url + merge-on-save

**Files:**
- Modify: `cloud/cito/config.py`
- Test: `cloud/tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

Append to `cloud/tests/test_config.py`:
```python
def test_calendar_url_round_trip(tmp_path):
    path = tmp_path / "cfg.json"
    saved = config.save_config({"calendar_url": "https://example.com/feed.ics"}, path)
    assert saved["calendar_url"] == "https://example.com/feed.ics"
    assert config.load_config(path)["calendar_url"] == "https://example.com/feed.ics"


def test_saving_calendar_url_preserves_voice(tmp_path):
    path = tmp_path / "cfg.json"
    config.save_config({"voice": "Be upbeat."}, path)
    config.save_config({"calendar_url": "https://example.com/feed.ics"}, path)
    cfg = config.load_config(path)
    assert cfg["voice"] == "Be upbeat."
    assert cfg["calendar_url"] == "https://example.com/feed.ics"


def test_load_default_includes_calendar_url(tmp_path):
    cfg = config.load_config(tmp_path / "missing.json")
    assert cfg["calendar_url"] == ""
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv --directory cloud run pytest tests/test_config.py -k calendar -v`
Expected: FAIL (`calendar_url` not in config; `save_config` replaces rather than merges).

- [ ] **Step 3: Implement**

In `cloud/cito/config.py`, replace `load_config` and `save_config` with:
```python
def load_config(path: Path = CONFIG_PATH) -> dict:
    base = {"voice": "", "preset": DEFAULT_PRESET, "calendar_url": ""}
    if Path(path).exists():
        base.update(json.loads(Path(path).read_text()))
    return base


def save_config(updates: dict, path: Path = CONFIG_PATH) -> dict:
    """Merge `updates` over the existing config so settings don't clobber each other."""
    cfg = load_config(path)
    cfg.update(updates)
    cfg["voice"] = validate_voice(cfg.get("voice", ""))
    cfg["calendar_url"] = (cfg.get("calendar_url") or "").strip()
    Path(path).write_text(json.dumps(cfg, indent=2))
    return cfg
```

- [ ] **Step 4: Run the config suite**

Run: `uv --directory cloud run pytest tests/test_config.py -v`
Expected: all PASS (existing + 3 new). The existing `save_config`/`load_config` tests still pass because the merge preserves their asserted keys.

- [ ] **Step 5: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add cloud/cito/config.py cloud/tests/test_config.py
git commit -m "Add calendar_url to config and merge-on-save"
```

---

## Task 3: CalendarSource

**Files:**
- Create: `cloud/cito/sources/calendar.py`
- Modify: `cloud/cito/sources/__init__.py`
- Test: `cloud/tests/test_calendar.py`

- [ ] **Step 1: Write the failing tests**

Create `cloud/tests/test_calendar.py`:
```python
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv --directory cloud run pytest tests/test_calendar.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cito.sources.calendar'`.

- [ ] **Step 3: Implement the source**

Create `cloud/cito/sources/calendar.py`:
```python
"""Calendar source — today's events from an iCal/.ics feed, with recurrence expansion.

Structured data queried by date (spec 3.6), a sibling to weather/stocks — NOT RAG.
"""

from datetime import date, datetime, time, timedelta

import httpx
import icalendar
import recurring_ical_events

from cito import config


def _fmt_time(dt: datetime) -> str:
    """Spoken-friendly clock time, e.g. '9 AM', '2:30 PM'."""
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

        today = date.today()
        start = datetime.combine(today, time.min)
        end = start + timedelta(days=1)
        occurrences = recurring_ical_events.of(cal).between(start, end)

        events = []
        for ev in occurrences:
            dtstart = ev.get("DTSTART").dt
            all_day = not isinstance(dtstart, datetime)
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
```

- [ ] **Step 4: Register the source**

In `cloud/cito/sources/__init__.py`, add the import and registry entry:
```python
"""Registry mapping a source key to its instance. Adding a source = one entry here."""

from cito.sources.calendar import CalendarSource
from cito.sources.stocks import StockSource
from cito.sources.weather import WeatherSource

SOURCES = {
    "weather": WeatherSource(),
    "stocks": StockSource(),
    "calendar": CalendarSource(),
}
```

- [ ] **Step 5: Run to verify they pass**

Run: `uv --directory cloud run pytest tests/test_calendar.py -v`
Expected: 4 PASS.
> If `recurring_ical_events.of(cal).between(start, end)` raises an API/signature error
> (library versions differ), keep the behavior identical but adjust to the installed
> version's call (e.g. `recurring_ical_events.of(cal).between(start.date(), end.date())`);
> do NOT change what the test asserts. If you cannot make it work, report BLOCKED.

- [ ] **Step 6: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add cloud/cito/sources/calendar.py cloud/cito/sources/__init__.py cloud/tests/test_calendar.py
git commit -m "Add CalendarSource (today's events from an iCal feed, recurrence)"
```

---

## Task 4: Console /calendar endpoint + /config exposure

**Files:**
- Modify: `cloud/cito/web/app.py`
- Test: `cloud/tests/test_web.py`

- [ ] **Step 1: Write the failing tests**

Append to `cloud/tests/test_web.py`:
```python
def test_config_includes_calendar_url(monkeypatch):
    from fastapi.testclient import TestClient
    from cito.web import app as webapp
    monkeypatch.setattr("cito.web.app.config.load_config",
                        lambda: {"voice": "", "preset": "Friendly", "calendar_url": "https://x/f.ics"})
    client = TestClient(webapp.app)
    assert client.get("/config").json()["calendar_url"] == "https://x/f.ics"


def test_post_calendar_saves_valid_url(monkeypatch):
    from fastapi.testclient import TestClient
    from cito.web import app as webapp
    saved = {}
    monkeypatch.setattr("cito.web.app.config.save_config",
                        lambda updates: saved.update(updates) or {"calendar_url": updates["calendar_url"]})
    client = TestClient(webapp.app)
    r = client.post("/calendar", json={"url": "https://example.com/feed.ics"})
    assert r.status_code == 200
    assert saved["calendar_url"] == "https://example.com/feed.ics"


def test_post_calendar_rejects_non_url():
    from fastapi.testclient import TestClient
    from cito.web import app as webapp
    client = TestClient(webapp.app)
    r = client.post("/calendar", json={"url": "not-a-url"})
    assert r.status_code == 400
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv --directory cloud run pytest tests/test_web.py -k calendar -v`
Expected: FAIL (`/calendar` route and `calendar_url` in `/config` don't exist).

- [ ] **Step 3: Implement**

In `cloud/cito/web/app.py`:

(a) Add a request model after `PreviewRequest`:
```python
class CalendarRequest(BaseModel):
    url: str = ""
```

(b) Add `calendar_url` to the `/config` response — replace the `get_config` body with:
```python
@app.get("/config")
def get_config() -> dict:
    cfg = config.load_config()
    return {"voice": cfg.get("voice", ""), "preset": cfg.get("preset", config.DEFAULT_PRESET),
            "presets": config.PRESETS, "calendar_url": cfg.get("calendar_url", "")}
```

(c) Add the `/calendar` route after `/voice`:
```python
@app.post("/calendar")
def save_calendar(req: CalendarRequest) -> dict:
    url = req.url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400, detail="Enter a valid http(s) calendar feed URL.")
    saved = config.save_config({"calendar_url": url})
    return {"ok": True, "calendar_url": saved["calendar_url"]}
```

- [ ] **Step 4: Run the web suite**

Run: `uv --directory cloud run pytest tests/test_web.py -v`
Expected: all PASS (existing + 3 new). Then `uv --directory cloud run ruff check .` → clean.

- [ ] **Step 5: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add cloud/cito/web/app.py cloud/tests/test_web.py
git commit -m "Add /calendar endpoint and calendar_url in /config"
```

---

## Task 5: Console UI — Calendar toggle + feed URL

**Files:**
- Modify: `cloud/cito/web/index.html`

- [ ] **Step 1: Add the Calendar checkbox**

In `cloud/cito/web/index.html`, in the Data pipelines `<fieldset>`, add a Calendar checkbox after the Stocks label:
```html
    <label><input type="checkbox" id="src-calendar" value="calendar" /> Calendar</label>
```

- [ ] **Step 2: Add the feed-URL field**

Immediately after the Data pipelines `</fieldset>` (and before the Document fieldset), add:
```html
  <fieldset>
    <legend>Calendar feed</legend>
    <input type="text" id="cal-url" placeholder="https://…/basic.ics"
           style="width:70%; padding:.4rem;" />
    <button id="cal-save">Save URL</button>
    <div id="cal-status" style="margin-top:.4rem; color:#555;"></div>
  </fieldset>
```

- [ ] **Step 3: Include calendar in selectedSources + wire the URL field**

Replace the `selectedSources()` function with (adds `calendar`):
```javascript
    function selectedSources() {
      return ["weather", "stocks", "calendar"].filter((s) => $("src-" + s).checked);
    }
```

In `loadConfig()`, after `$("voice").value = cfg.voice || "";`, add:
```javascript
      $("cal-url").value = cfg.calendar_url || "";
```

Add a save handler — put it right after the `loadConfig();` call line:
```javascript
    $("cal-save").onclick = async () => {
      $("cal-status").textContent = "Saving calendar URL...";
      const r = await fetch("/calendar", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ url: $("cal-url").value }),
      });
      if (!r.ok) { $("cal-status").textContent = "Rejected: " + ((await r.json()).detail || "bad URL"); return; }
      const data = await r.json();
      $("cal-url").value = data.calendar_url;
      $("cal-status").textContent = "Calendar URL saved.";
    };
```

- [ ] **Step 4: Smoke-test the page + routes**

Run (one command):
```bash
cd /Users/dwightbritton/Desktop/Cito
uv --directory cloud run uvicorn cito.web.app:app --port 8014 & SRV=$!
sleep 4
curl -s -o /dev/null -w "GET / -> %{http_code}\n" http://127.0.0.1:8014/
curl -s -X POST http://127.0.0.1:8014/calendar -H 'Content-Type: application/json' -d '{"url":"not-a-url"}' -o /dev/null -w "/calendar bad -> %{http_code} (expect 400)\n"
kill $SRV
```
Expected: `GET / -> 200` and `/calendar bad -> 400`.

- [ ] **Step 5: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add cloud/cito/web/index.html
git commit -m "Add Calendar toggle and feed-URL field to the console"
```

---

## Task 6: Live verification + README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Verify the source is wired (no real feed needed)**

Run:
```bash
cd /Users/dwightbritton/Desktop/Cito
uv --directory cloud run python -c "from cito.sources import SOURCES; print(sorted(SOURCES))"
uv --directory cloud run python -m cito.run announce --source calendar --print 2>&1 | tail -2
```
Expected: the source list includes `calendar`. The announce run, with no `calendar_url` configured, skips the calendar source (it raises and the pipeline skips it) — so it prints either a template line or, with no other source, errors that no fragments were produced; that is acceptable. (A real end-to-end check with a feed URL happens in the live console pass.)

- [ ] **Step 2: Update the README**

In `README.md`, under "Running the Phase 1 console", after the document paragraph, add:
```markdown
Connect a **calendar**: paste a subscribe-able iCal/`.ics` feed URL into the Calendar feed
field and Save, then tick **Calendar** — it reads **today's** events (recurring ones included)
and combines into one announcement like any other source. (Event-driven triggers and OAuth
calendars come later.)
```

- [ ] **Step 3: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add README.md
git commit -m "Document the calendar feed feature"
```

---

## Exit Criteria (verify all)

- [ ] `SOURCES` includes `calendar`; `--source calendar` and the console Calendar checkbox both work.
- [ ] With a real iCal URL saved, ticking Calendar produces an announcement of today's events (including a recurring one), played in VLC.
- [ ] Calendar combines with Weather/Stocks/a document into one announcement; unticking leaves it out.
- [ ] An empty day → the "no events scheduled today" line; a missing/broken feed is skipped without sinking the announcement.
- [ ] Saving a calendar URL does not wipe the saved voice (config merge).
- [ ] `uv --directory cloud run pytest -q` all green; `ruff check .` clean.
