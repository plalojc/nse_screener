from __future__ import annotations

import time
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


def _run_scheduled_scan(source: str = "scheduler"):
    """Start the daily scan if its report does not already exist. Returns the job."""
    report_date = _scheduled_report_date()
    try:
        from .reports import report_exists

        if report_exists(report_date):
            set_setting("scheduler_last_report_date", report_date)
            print(f"[Scheduler] Report already exists for {report_date}; skipping scheduled scan.")
            return None
        job = jobs.start_scan(scan_date=report_date, user_email=None)
        set_setting("scheduler_last_report_date", report_date)
        print(f"[Scheduler] Started scheduled scan for {report_date} from {source}: {job.id}")
        return job
    except Exception as exc:
        print(f"[Scheduler] Failed to start scheduled scan for {report_date}: {exc}")
        return None


def _wait_for_job(job_id: str, timeout: float) -> str:
    """Block until the job reaches a terminal state or timeout. Keeps the
    Cloudflare container alive (active request) for the cron-triggered scan."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = jobs.get(job_id)
        if job and job.status in {"success", "failed"}:
            return job.status
        time.sleep(3)
    return "timeout"


def run_due_schedule_check(block: bool = False, timeout: float = 840.0) -> dict[str, Any]:
    """Run the daily scan if it is due and not already done.

    block=True waits for the scan to finish (used by the cron tick so the
    container stays awake for the whole run). Returns a small status dict.
    """
    if get_setting("scheduler_enabled", "false") != "true":
        return {"status": "disabled"}
    scan_time = get_setting("scheduler_time", "08:20")
    try:
        hour, minute = [int(part) for part in scan_time.split(":", 1)]
    except ValueError:
        return {"status": "bad_time"}

    now = datetime.now(IST)
    if now.weekday() >= 5:
        return {"status": "weekend"}
    scheduled_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now < scheduled_at:
        return {"status": "not_yet", "scheduled_at": scheduled_at.isoformat()}

    report_date = _scheduled_report_date(now)
    if get_setting("scheduler_last_report_date", "") == report_date:
        return {"status": "already_done", "report_date": report_date}

    from .reports import report_exists

    if report_exists(report_date):
        set_setting("scheduler_last_report_date", report_date)
        return {"status": "already_exists", "report_date": report_date}

    running = [j for j in jobs.list_jobs() if j.get("status") in {"queued", "running"}]
    job_id = running[0].get("id") if running else getattr(_run_scheduled_scan("catch-up"), "id", None)
    if not job_id:
        return {"status": "skipped", "report_date": report_date}

    if block:
        return {"status": _wait_for_job(job_id, timeout), "report_date": report_date, "job_id": job_id}
    return {"status": "started", "report_date": report_date, "job_id": job_id}


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
