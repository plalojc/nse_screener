from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler

from .scanner_runner import ScannerJobManager
from .store import get_setting, set_setting


jobs = ScannerJobManager()
scheduler = BackgroundScheduler(timezone="Asia/Kolkata")
IST = ZoneInfo("Asia/Kolkata")


def _previous_weekday(day):
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def _scheduled_report_date(now: datetime | None = None) -> str:
    now = now or datetime.now(IST)
    target = now.date() if now.hour >= 17 else now.date() - timedelta(days=1)
    return _previous_weekday(target).isoformat()


def _run_scheduled_scan(source: str = "scheduler") -> None:
    report_date = _scheduled_report_date()
    try:
        from .reports import report_exists

        if report_exists(report_date):
            set_setting("scheduler_last_report_date", report_date)
            print(f"[Scheduler] Report already exists for {report_date}; skipping scheduled scan.")
            return
        job = jobs.start_scan(scan_date=report_date, user_email=None)
        set_setting("scheduler_last_report_date", report_date)
        print(f"[Scheduler] Started scheduled scan for {report_date} from {source}: {job.id}")
    except Exception as exc:
        print(f"[Scheduler] Failed to start scheduled scan for {report_date}: {exc}")


def run_due_schedule_check() -> None:
    if get_setting("scheduler_enabled", "false") != "true":
        return
    scan_time = get_setting("scheduler_time", "08:20")
    try:
        hour, minute = [int(part) for part in scan_time.split(":", 1)]
    except ValueError:
        return

    now = datetime.now(IST)
    if now.weekday() >= 5:
        return
    scheduled_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now < scheduled_at:
        return

    report_date = _scheduled_report_date(now)
    if get_setting("scheduler_last_report_date", "") == report_date:
        return

    from .reports import report_exists

    if report_exists(report_date):
        set_setting("scheduler_last_report_date", report_date)
        return
    if any(job.get("status") in {"queued", "running"} for job in jobs.list_jobs()):
        return
    _run_scheduled_scan("catch-up")


def apply_schedule(scan_time: str) -> None:
    hour, minute = [int(part) for part in scan_time.split(":", 1)]
    if scheduler.get_job("daily_scan"):
        scheduler.remove_job("daily_scan")
    scheduler.add_job(
        lambda: _run_scheduled_scan("cron"),
        "cron",
        id="daily_scan",
        day_of_week="mon-fri",
        hour=hour,
        minute=minute,
        misfire_grace_time=3600,
        coalesce=True,
        replace_existing=True,
    )


def scheduler_state() -> dict[str, Any]:
    enabled = get_setting("scheduler_enabled", "false") == "true"
    scan_time = get_setting("scheduler_time", "08:20")
    if enabled:
        run_due_schedule_check()
    job = scheduler.get_job("daily_scan")
    return {
        "enabled": enabled,
        "time": scan_time,
        "next_run_time": job.next_run_time.isoformat() if job and job.next_run_time else None,
    }


def update_scheduler(enabled: bool, scan_time: str) -> dict[str, Any]:
    set_setting("scheduler_enabled", "true" if enabled else "false")
    set_setting("scheduler_time", scan_time)
    if enabled:
        apply_schedule(scan_time)
    elif scheduler.get_job("daily_scan"):
        scheduler.remove_job("daily_scan")
    return scheduler_state()
