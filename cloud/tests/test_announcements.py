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
