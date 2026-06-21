"""APScheduler wrapper: fire saved announcements through the existing pipeline.

The scheduler lives in the web process; jobs fire only while the console runs.
"""

import tzlocal
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from cito import announcements, pipeline

# A DST-aware local zone (not a fixed offset), so "8:30 AM" stays 8:30 across DST changes.
_LOCAL_TZ = tzlocal.get_localzone()
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
