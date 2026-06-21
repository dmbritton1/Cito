# Phase 2a — Scheduler + Announcement Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Save announcements to a JSON store, fire them on a cron schedule with APScheduler, and manage them (create/list/edit/delete/run-now) from a console page — all through the existing pipeline.

**Architecture:** `announcements.py` persists records + CRUD; `scheduler.py` wraps an APScheduler BackgroundScheduler that registers a cron job per record and fires it via the existing pipeline; `web/app.py` exposes CRUD + run endpoints and starts the scheduler on app startup; a new `announcements.html` page drives it.

**Tech Stack:** Python 3.11+ (uv), APScheduler, FastAPI, pytest, ruff. Run commands with `uv --directory cloud run ...` (do NOT `cd` into cloud).

---

## File Structure

```
cloud/cito/announcements.py    (new)  records + JSON store + CRUD + validate
cloud/cito/scheduler.py        (new)  BackgroundScheduler: _trigger, run_announcement, reschedule, unschedule, start
cloud/cito/web/app.py          (mod)  /announcements CRUD + /run + /announcements-ui; start scheduler on startup
cloud/cito/web/announcements.html (new) management page
cloud/cito/web/index.html      (mod)  link to the Announcements page
cloud/pyproject.toml           (mod)  + APScheduler
.gitignore                     (mod)  announcements.json
cloud/tests/test_announcements.py (new)
cloud/tests/test_scheduler.py     (new)
cloud/tests/test_web.py           (mod)  announcement endpoints
```

---

## Task 1: Dependency + gitignore

**Files:**
- Modify: `cloud/pyproject.toml`, `.gitignore`

- [ ] **Step 1: Add APScheduler**

In `cloud/pyproject.toml` `[project].dependencies`, append `"APScheduler"` after `"recurring-ical-events"`.

- [ ] **Step 2: Ignore the store file**

In `.gitignore`, under the "Runtime app config" comment, add a line:
```
announcements.json
```

- [ ] **Step 3: Sync and verify**

Run:
```bash
uv --directory cloud sync
uv --directory cloud run python -c "import apscheduler; print('ok')"
```
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add cloud/pyproject.toml cloud/uv.lock .gitignore
git commit -m "Add APScheduler dep and ignore announcements.json"
```

---

## Task 2: announcements.py — records + CRUD

**Files:**
- Create: `cloud/cito/announcements.py`
- Test: `cloud/tests/test_announcements.py`

- [ ] **Step 1: Write the failing tests**

Create `cloud/tests/test_announcements.py`:
```python
import pytest

from cito import announcements
from cito.announcements import AnnouncementError, AnnouncementNotFound

VALID = {
    "name": "Morning briefing", "kind": "sources",
    "sources": ["weather", "calendar"], "time": "08:30",
    "days": ["mon", "tue", "wed", "thu", "fri"],
}


def test_create_and_list_round_trip(tmp_path):
    p = tmp_path / "a.json"
    rec = announcements.create(VALID, p)
    assert rec["id"]
    assert announcements.list_announcements(p) == [rec]


def test_create_assigns_unique_ids(tmp_path):
    p = tmp_path / "a.json"
    a = announcements.create(VALID, p)
    b = announcements.create(VALID, p)
    assert a["id"] != b["id"]


def test_message_kind_round_trip(tmp_path):
    p = tmp_path / "a.json"
    rec = announcements.create(
        {"name": "Standup", "kind": "message", "message": "Standup in five minutes.",
         "time": "09:55", "days": ["mon"]}, p)
    assert rec["kind"] == "message"
    assert rec["message"] == "Standup in five minutes."
    assert rec["sources"] == []


def test_update_replaces(tmp_path):
    p = tmp_path / "a.json"
    rec = announcements.create(VALID, p)
    updated = announcements.update(rec["id"], {**VALID, "name": "Renamed"}, p)
    assert updated["id"] == rec["id"]
    assert announcements.get(rec["id"], p)["name"] == "Renamed"


def test_delete_removes(tmp_path):
    p = tmp_path / "a.json"
    rec = announcements.create(VALID, p)
    announcements.delete(rec["id"], p)
    assert announcements.list_announcements(p) == []


def test_get_missing_raises_not_found(tmp_path):
    with pytest.raises(AnnouncementNotFound):
        announcements.get("nope", tmp_path / "a.json")


@pytest.mark.parametrize("bad", [
    {**VALID, "time": "25:00"},
    {**VALID, "days": []},
    {**VALID, "sources": ["bogus"]},
    {**VALID, "name": "  "},
    {"name": "x", "kind": "message", "message": "  ", "time": "08:30", "days": ["mon"]},
    {**VALID, "kind": "other"},
])
def test_validation_rejects_bad(bad, tmp_path):
    with pytest.raises(AnnouncementError):
        announcements.create(bad, tmp_path / "a.json")
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv --directory cloud run pytest tests/test_announcements.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cito.announcements'`.

- [ ] **Step 3: Implement**

Create `cloud/cito/announcements.py`:
```python
"""Persisted announcement records (scheduled + run-on-demand) in a JSON store."""

import json
import re
import uuid
from pathlib import Path

STORE_PATH = Path(__file__).parent.parent / "announcements.json"  # cloud/announcements.json
VALID_SOURCES = {"weather", "stocks", "calendar"}
VALID_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class AnnouncementError(ValueError):
    """A bad announcement record; the message is admin-facing."""


class AnnouncementNotFound(AnnouncementError):
    """No announcement with the given id."""


def _load(path: Path) -> list:
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else []


def _save(items: list, path: Path) -> None:
    Path(path).write_text(json.dumps(items, indent=2))


def validate(data: dict) -> dict:
    name = (data.get("name") or "").strip()
    if not name:
        raise AnnouncementError("Name is required.")
    kind = data.get("kind")
    if kind not in ("sources", "message"):
        raise AnnouncementError("Kind must be 'sources' or 'message'.")
    sources = data.get("sources") or []
    message = (data.get("message") or "").strip()
    if kind == "sources":
        if not sources or any(s not in VALID_SOURCES for s in sources):
            raise AnnouncementError("Choose at least one valid source.")
    elif not message:
        raise AnnouncementError("Message text is required.")
    time = (data.get("time") or "").strip()
    if not _TIME_RE.match(time):
        raise AnnouncementError("Time must be HH:MM (24-hour).")
    days = data.get("days") or []
    if not days or any(d not in VALID_DAYS for d in days):
        raise AnnouncementError("Choose at least one valid day.")
    return {
        "name": name,
        "kind": kind,
        "sources": sources if kind == "sources" else [],
        "message": message if kind == "message" else "",
        "time": time,
        "days": days,
    }


def list_announcements(path: Path = STORE_PATH) -> list:
    return _load(path)


def get(ann_id: str, path: Path = STORE_PATH) -> dict:
    for item in _load(path):
        if item["id"] == ann_id:
            return item
    raise AnnouncementNotFound(f"No announcement with id {ann_id}.")


def create(data: dict, path: Path = STORE_PATH) -> dict:
    rec = validate(data)
    rec["id"] = uuid.uuid4().hex
    items = _load(path)
    items.append(rec)
    _save(items, path)
    return rec


def update(ann_id: str, data: dict, path: Path = STORE_PATH) -> dict:
    rec = validate(data)
    rec["id"] = ann_id
    items = _load(path)
    for i, item in enumerate(items):
        if item["id"] == ann_id:
            items[i] = rec
            _save(items, path)
            return rec
    raise AnnouncementNotFound(f"No announcement with id {ann_id}.")


def delete(ann_id: str, path: Path = STORE_PATH) -> None:
    items = _load(path)
    kept = [i for i in items if i["id"] != ann_id]
    if len(kept) == len(items):
        raise AnnouncementNotFound(f"No announcement with id {ann_id}.")
    _save(kept, path)
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv --directory cloud run pytest tests/test_announcements.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add cloud/cito/announcements.py cloud/tests/test_announcements.py
git commit -m "Add announcement records + JSON store CRUD"
```

---

## Task 3: scheduler.py — APScheduler wrapper

**Files:**
- Create: `cloud/cito/scheduler.py`
- Test: `cloud/tests/test_scheduler.py`

- [ ] **Step 1: Write the failing tests**

Create `cloud/tests/test_scheduler.py`:
```python
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
    monkeypatch.setattr("cito.scheduler.pipeline.generate_announcement",
                        lambda sources: calls.setdefault("gen", sources) or "GENERATED")
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv --directory cloud run pytest tests/test_scheduler.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cito.scheduler'`.

- [ ] **Step 3: Implement**

Create `cloud/cito/scheduler.py`:
```python
"""APScheduler wrapper: fire saved announcements through the existing pipeline.

The scheduler lives in the web process; jobs fire only while the console runs.
"""

from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from cito import announcements, pipeline

_LOCAL_TZ = datetime.now().astimezone().tzinfo
_scheduler = BackgroundScheduler(timezone=_LOCAL_TZ)


def _trigger(record: dict) -> CronTrigger:
    hour, minute = record["time"].split(":")
    return CronTrigger(
        day_of_week=",".join(record["days"]),
        hour=int(hour),
        minute=int(minute),
        timezone=_LOCAL_TZ,
    )


def run_announcement(record: dict) -> str:
    """Generate (or take the verbatim message) and send. Returns the spoken text."""
    if record["kind"] == "sources":
        text = pipeline.generate_announcement(record["sources"])
    else:
        text = record["message"]
    pipeline.send_announcement(text)
    return text


def reschedule(record: dict) -> None:
    _scheduler.add_job(run_announcement, _trigger(record), args=[record],
                       id=record["id"], replace_existing=True)


def unschedule(ann_id: str) -> None:
    if _scheduler.get_job(ann_id):
        _scheduler.remove_job(ann_id)


def start() -> None:
    """Start the scheduler (idempotent) and register all saved announcements."""
    if not _scheduler.running:
        _scheduler.start()
    for rec in announcements.list_announcements():
        reschedule(rec)
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv --directory cloud run pytest tests/test_scheduler.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add cloud/cito/scheduler.py cloud/tests/test_scheduler.py
git commit -m "Add APScheduler wrapper firing announcements via the pipeline"
```

---

## Task 4: Web endpoints + scheduler startup

**Files:**
- Modify: `cloud/cito/web/app.py`
- Test: `cloud/tests/test_web.py`

- [ ] **Step 1: Write the failing tests**

Append to `cloud/tests/test_web.py`:
```python
def test_list_announcements(monkeypatch):
    from fastapi.testclient import TestClient
    from cito.web import app as webapp
    monkeypatch.setattr("cito.web.app.announcements.list_announcements", lambda: [{"id": "x"}])
    client = TestClient(webapp.app)
    assert client.get("/announcements").json() == [{"id": "x"}]


def test_create_announcement_schedules_it(monkeypatch):
    from fastapi.testclient import TestClient
    from cito.web import app as webapp
    rec = {"id": "x", "name": "Brief", "kind": "sources", "sources": ["weather"],
           "message": "", "time": "08:30", "days": ["mon"]}
    scheduled = {}
    monkeypatch.setattr("cito.web.app.announcements.create", lambda data: rec)
    monkeypatch.setattr("cito.web.app.scheduler.reschedule", lambda r: scheduled.update(r))
    client = TestClient(webapp.app)
    r = client.post("/announcements", json={"name": "Brief", "kind": "sources",
                    "sources": ["weather"], "time": "08:30", "days": ["mon"]})
    assert r.status_code == 200
    assert r.json()["id"] == "x"
    assert scheduled["id"] == "x"


def test_create_bad_returns_400(monkeypatch):
    from fastapi.testclient import TestClient
    from cito.web import app as webapp
    from cito.announcements import AnnouncementError

    def boom(data):
        raise AnnouncementError("Time must be HH:MM (24-hour).")
    monkeypatch.setattr("cito.web.app.announcements.create", boom)
    client = TestClient(webapp.app)
    r = client.post("/announcements", json={"name": "x", "kind": "sources",
                    "sources": ["weather"], "time": "99:99", "days": ["mon"]})
    assert r.status_code == 400


def test_delete_unknown_returns_404(monkeypatch):
    from fastapi.testclient import TestClient
    from cito.web import app as webapp
    from cito.announcements import AnnouncementNotFound

    def boom(ann_id):
        raise AnnouncementNotFound("nope")
    monkeypatch.setattr("cito.web.app.announcements.delete", boom)
    client = TestClient(webapp.app)
    assert client.delete("/announcements/nope").status_code == 404


def test_run_announcement_now(monkeypatch):
    from fastapi.testclient import TestClient
    from cito.web import app as webapp
    rec = {"id": "x", "kind": "message", "message": "Hi", "sources": [],
           "name": "n", "time": "08:30", "days": ["mon"]}
    monkeypatch.setattr("cito.web.app.announcements.get", lambda ann_id: rec)
    monkeypatch.setattr("cito.web.app.scheduler.run_announcement", lambda r: "SPOKEN")
    client = TestClient(webapp.app)
    r = client.post("/announcements/x/run")
    assert r.json() == {"ok": True, "text": "SPOKEN"}
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv --directory cloud run pytest tests/test_web.py -k announcement -v`
Expected: FAIL (routes/imports don't exist).

- [ ] **Step 3: Implement**

In `cloud/cito/web/app.py`:

(a) Add `asynccontextmanager` import at the top and extend the cito import:
```python
from contextlib import asynccontextmanager
```
Change `from cito import config, documents, pipeline` to:
```python
from cito import announcements, config, documents, pipeline, scheduler
from cito.announcements import AnnouncementError, AnnouncementNotFound
```

(b) Replace the `app = FastAPI(title="Cito Console")` line with a lifespan that starts the scheduler:
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start()
    yield


app = FastAPI(title="Cito Console", lifespan=lifespan)
```

(c) Add the request model after `CalendarRequest`:
```python
class AnnouncementBody(BaseModel):
    name: str = ""
    kind: str = "sources"
    sources: list[str] = []
    message: str = ""
    time: str = ""
    days: list[str] = []
```

(d) Add the routes after the `/upload` route:
```python
@app.get("/announcements")
def list_announcements() -> list:
    return announcements.list_announcements()


@app.post("/announcements")
def create_announcement(body: AnnouncementBody) -> dict:
    try:
        rec = announcements.create(body.model_dump())
    except AnnouncementError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    scheduler.reschedule(rec)
    return rec


@app.put("/announcements/{ann_id}")
def update_announcement(ann_id: str, body: AnnouncementBody) -> dict:
    try:
        rec = announcements.update(ann_id, body.model_dump())
    except AnnouncementNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AnnouncementError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    scheduler.reschedule(rec)
    return rec


@app.delete("/announcements/{ann_id}")
def delete_announcement(ann_id: str) -> dict:
    try:
        announcements.delete(ann_id)
    except AnnouncementNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    scheduler.unschedule(ann_id)
    return {"ok": True}


@app.post("/announcements/{ann_id}/run")
def run_announcement_now(ann_id: str) -> dict:
    try:
        rec = announcements.get(ann_id)
    except AnnouncementNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "text": scheduler.run_announcement(rec)}


@app.get("/announcements-ui", response_class=HTMLResponse)
def announcements_ui() -> str:
    return (Path(__file__).parent / "announcements.html").read_text()
```

- [ ] **Step 4: Run the web suite**

Run: `uv --directory cloud run pytest tests/test_web.py -v`
Expected: all PASS (existing + 5 new). Then `uv --directory cloud run ruff check .` → clean.
(Existing web tests construct `TestClient(app)` WITHOUT a `with` block, so the lifespan/scheduler does not start during tests — they stay green and no scheduler thread leaks.)

- [ ] **Step 5: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add cloud/cito/web/app.py cloud/tests/test_web.py
git commit -m "Add announcement CRUD/run endpoints and scheduler startup"
```

---

## Task 5: Announcements management page

**Files:**
- Create: `cloud/cito/web/announcements.html`
- Modify: `cloud/cito/web/index.html`

- [ ] **Step 1: Create the page**

Create `cloud/cito/web/announcements.html`:
```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Cito — Announcements</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; }
    h1 { font-size: 1.4rem; }
    fieldset { border: 1px solid #ccc; border-radius: 8px; margin-bottom: 1rem; }
    button { font-size: .95rem; padding: .35rem .8rem; margin-right: .4rem; cursor: pointer; }
    input[type=text], textarea { width: 100%; padding: .4rem; box-sizing: border-box; }
    label { margin-right: .8rem; }
    table { width: 100%; border-collapse: collapse; margin-bottom: 1rem; }
    td, th { text-align: left; padding: .4rem; border-bottom: 1px solid #eee; vertical-align: top; }
    #status { margin-top: 1rem; color: #555; min-height: 1.2rem; }
    .muted { color: #777; font-size: .9rem; }
  </style>
</head>
<body>
  <h1>Cito — Scheduled Announcements</h1>
  <p><a href="/">← Back to console</a></p>

  <table id="list"><thead>
    <tr><th>Name</th><th>When</th><th>What</th><th>Actions</th></tr>
  </thead><tbody id="rows"></tbody></table>

  <fieldset>
    <legend>New / edit announcement</legend>
    <input type="hidden" id="edit-id" />
    <p><label>Name <input type="text" id="f-name" /></label></p>
    <p>
      <label><input type="radio" name="kind" value="sources" checked /> Sources</label>
      <label><input type="radio" name="kind" value="message" /> Fixed message</label>
    </p>
    <p id="sources-row">
      <label><input type="checkbox" id="s-weather" value="weather" /> Weather</label>
      <label><input type="checkbox" id="s-stocks" value="stocks" /> Stocks</label>
      <label><input type="checkbox" id="s-calendar" value="calendar" /> Calendar</label>
    </p>
    <p id="message-row" style="display:none;">
      <textarea id="f-message" placeholder="Reminder text spoken verbatim..."></textarea>
    </p>
    <p><label>Time <input type="text" id="f-time" placeholder="08:30" style="width:6rem;" /></label>
       <span class="muted">24-hour HH:MM, local time</span></p>
    <p id="days-row"></p>
    <button id="save">Save</button>
    <button id="reset">Clear form</button>
  </fieldset>
  <div id="status"></div>

  <script>
    const $ = (id) => document.getElementById(id);
    const status = (m) => { $("status").textContent = m; };
    const DAYS = ["mon","tue","wed","thu","fri","sat","sun"];

    DAYS.forEach((d) => {
      const l = document.createElement("label");
      l.innerHTML = `<input type="checkbox" class="day" value="${d}" /> ${d}`;
      $("days-row").appendChild(l);
    });

    function selectedKind() {
      return document.querySelector("input[name=kind]:checked").value;
    }
    function syncKindRows() {
      $("sources-row").style.display = selectedKind() === "sources" ? "block" : "none";
      $("message-row").style.display = selectedKind() === "message" ? "block" : "none";
    }
    document.querySelectorAll("input[name=kind]").forEach((r) => r.onchange = syncKindRows);

    function readForm() {
      const kind = selectedKind();
      return {
        name: $("f-name").value,
        kind,
        sources: ["weather","stocks","calendar"].filter((s) => $("s-" + s).checked),
        message: $("f-message").value,
        time: $("f-time").value,
        days: DAYS.filter((d) => document.querySelector(`.day[value=${d}]`).checked),
      };
    }
    function resetForm() {
      $("edit-id").value = "";
      $("f-name").value = ""; $("f-message").value = ""; $("f-time").value = "";
      document.querySelectorAll(".day, #s-weather, #s-stocks, #s-calendar").forEach((c) => c.checked = false);
      document.querySelector("input[name=kind][value=sources]").checked = true;
      syncKindRows();
    }
    $("reset").onclick = resetForm;

    function fillForm(rec) {
      $("edit-id").value = rec.id;
      $("f-name").value = rec.name;
      document.querySelector(`input[name=kind][value=${rec.kind}]`).checked = true;
      syncKindRows();
      ["weather","stocks","calendar"].forEach((s) => $("s-" + s).checked = rec.sources.includes(s));
      $("f-message").value = rec.message || "";
      $("f-time").value = rec.time;
      DAYS.forEach((d) => document.querySelector(`.day[value=${d}]`).checked = rec.days.includes(d));
    }

    async function load() {
      const items = await (await fetch("/announcements")).json();
      $("rows").innerHTML = "";
      for (const rec of items) {
        const what = rec.kind === "sources" ? rec.sources.join(", ") : "“" + rec.message + "”";
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>${rec.name}</td><td>${rec.time} · ${rec.days.join(",")}</td>` +
          `<td>${what}</td><td></td>`;
        const actions = tr.lastElementChild;
        const mk = (label, fn) => { const b = document.createElement("button"); b.textContent = label; b.onclick = fn; actions.appendChild(b); };
        mk("Run now", async () => { status("Running " + rec.name + "..."); const r = await fetch(`/announcements/${rec.id}/run`, {method:"POST"}); const d = await r.json(); status(r.ok ? "Ran: " + d.text : "Run failed"); });
        mk("Edit", () => { fillForm(rec); window.scrollTo(0, document.body.scrollHeight); });
        mk("Delete", async () => { await fetch(`/announcements/${rec.id}`, {method:"DELETE"}); status("Deleted."); load(); });
        $("rows").appendChild(tr);
      }
    }

    $("save").onclick = async () => {
      const id = $("edit-id").value;
      const url = id ? `/announcements/${id}` : "/announcements";
      const method = id ? "PUT" : "POST";
      status("Saving...");
      const r = await fetch(url, { method, headers: {"Content-Type":"application/json"}, body: JSON.stringify(readForm()) });
      if (!r.ok) { status("Rejected: " + ((await r.json()).detail || "invalid")); return; }
      status("Saved."); resetForm(); load();
    };

    syncKindRows();
    load();
  </script>
</body>
</html>
```

- [ ] **Step 2: Link it from the console**

In `cloud/cito/web/index.html`, just after the `<h1>Cito — Announcement Console</h1>` line, add:
```html
  <p><a href="/announcements-ui">→ Scheduled announcements</a></p>
```

- [ ] **Step 3: Smoke-test both pages + the list route**

Run (one command):
```bash
cd /Users/dwightbritton/Desktop/Cito
uv --directory cloud run uvicorn cito.web.app:app --port 8015 & SRV=$!
sleep 4
curl -s -o /dev/null -w "/ -> %{http_code}\n" http://127.0.0.1:8015/
curl -s -o /dev/null -w "/announcements-ui -> %{http_code}\n" http://127.0.0.1:8015/announcements-ui
curl -s -w "\n/announcements -> ok\n" http://127.0.0.1:8015/announcements
kill $SRV
```
Expected: `/ -> 200`, `/announcements-ui -> 200`, and `/announcements` returns `[]` (or saved records).

- [ ] **Step 4: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add cloud/cito/web/announcements.html cloud/cito/web/index.html
git commit -m "Add Announcements management page"
```

---

## Task 6: README + live verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the README**

In `README.md`, under "Running the Phase 1 console", after the calendar paragraph, add:
```markdown
Open **Scheduled announcements** (linked from the console) to save announcements that fire
automatically: pick **Sources** (generated fresh each time) or a **fixed message**, set a
time + days, and Save. **Run now** fires any of them immediately for testing. Note: the
scheduler runs inside the console process, so run uvicorn **without `--reload`** for
scheduling, and jobs fire only while the server is up.
```

- [ ] **Step 2: Live verification (manual)**

Run the console WITHOUT --reload:
```bash
cd /Users/dwightbritton/Desktop/Cito
uv --directory cloud run uvicorn cito.web.app:app --port 8000
```
In a browser at `http://127.0.0.1:8000/announcements-ui`: create a **message** announcement
("Test reminder.") scheduled one or two minutes ahead on today's weekday; with VLC listening
on `rtp://@224.0.1.75:10000`, confirm it fires and plays at that minute. Also click **Run now**
on it to confirm immediate firing. Stop the server with Ctrl-C when done.
(If Gemma/sources are involved and unavailable, the template fallback still produces audio.)

- [ ] **Step 3: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add README.md
git commit -m "Document the scheduler and announcement management"
```

---

## Exit Criteria (verify all)

- [ ] A saved source-based announcement fires automatically at its time and plays in VLC (server running, no --reload).
- [ ] A fixed-message announcement fires verbatim on schedule.
- [ ] "Run now" fires any saved announcement immediately.
- [ ] Create/edit/delete persist to `announcements.json` and re-register on restart (startup loads them).
- [ ] Bad input → 400; unknown id → 404.
- [ ] `uv --directory cloud run pytest -q` all green; `ruff check .` clean.
