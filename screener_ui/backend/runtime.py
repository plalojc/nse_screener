from __future__ import annotations

from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler

from .scanner_runner import ScannerJobManager
from .store import get_setting, set_setting


jobs = ScannerJobManager()
scheduler = BackgroundScheduler(timezone="Asia/Kolkata")


def apply_schedule(scan_time: str) -> None:
    hour, minute = [int(part) for part in scan_time.split(":", 1)]
    if scheduler.get_job("daily_scan"):
        scheduler.remove_job("daily_scan")
    scheduler.add_job(
        lambda: jobs.start_scan(),
        "cron",
        id="daily_scan",
        day_of_week="mon-fri",
        hour=hour,
        minute=minute,
        replace_existing=True,
    )


def scheduler_state() -> dict[str, Any]:
    enabled = get_setting("scheduler_enabled", "false") == "true"
    scan_time = get_setting("scheduler_time", "08:20")
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
