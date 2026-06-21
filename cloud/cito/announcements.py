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
    items = _load(path)
    for i, item in enumerate(items):
        if item["id"] == ann_id:
            rec = validate(data)
            rec["id"] = ann_id
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
