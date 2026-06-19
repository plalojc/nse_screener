from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..auth import CurrentUser, current_user, verify_token
from ..reports import report_exists
from ..runtime import jobs
from ..scanner_runner import sse_event


router = APIRouter(prefix="/scan")


class ScanRequest(BaseModel):
    scan_date: str | None = None
    force_refresh: bool = False


def _effective_report_date(scan_date: str | None) -> str:
    if scan_date:
        target = datetime.strptime(scan_date, "%Y-%m-%d").date()
    else:
        now = datetime.now()
        target = date.today() if now.hour >= 17 else date.today() - timedelta(days=1)

    today = date.today()
    if target >= today and datetime.now().hour < 17:
        target = today - timedelta(days=1)

    while target.weekday() >= 5:
        target -= timedelta(days=1)
    return target.isoformat()


@router.post("/run")
def run_scan(payload: ScanRequest, user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    effective_date = _effective_report_date(payload.scan_date)
    if report_exists(effective_date):
        return {
            "id": None,
            "status": "skipped",
            "progress": 100,
            "message": f"Report already exists for {effective_date}. Delete that report before running the scan again.",
            "started_at": None,
            "ended_at": None,
            "exit_code": 0,
            "lines": [
                f"Requested date: {payload.scan_date or effective_date}.",
                f"Effective trading date: {effective_date}.",
                f"Report already exists for {effective_date}.",
                "Delete the existing report from Reports page before running this scan again.",
            ],
            "command": [],
            "existing_report": {
                "date": effective_date,
                "kind": "scan",
                "filename": f"NSE-Breakout-{effective_date}.html",
            },
        }
    job = jobs.start_scan(scan_date=payload.scan_date, force_refresh=payload.force_refresh, user_email=user.email)
    return job.snapshot()


@router.get("/jobs")
def scan_jobs(user: CurrentUser = Depends(current_user)) -> list[dict[str, Any]]:
    return jobs.list_jobs()


@router.get("/jobs/{job_id}")
def scan_job(job_id: str, user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Scan job not found")
    return job.snapshot()


@router.get("/jobs/{job_id}/events")
async def scan_events(job_id: str, token: str | None = None) -> StreamingResponse:
    if token:
        verify_token(token, "access")
    else:
        raise HTTPException(status_code=401, detail="Login required")
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Scan job not found")

    async def generate():
        sent = 0
        yield sse_event("snapshot", job.snapshot())
        while True:
            while sent < len(job.lines):
                line = job.lines[sent]
                sent += 1
                yield sse_event("line", {"line": line, "progress": job.progress, "status": job.status})
            yield sse_event("snapshot", job.snapshot())
            if job.status in {"success", "failed"} and sent >= len(job.lines):
                break
            await asyncio.sleep(0.8)

    return StreamingResponse(generate(), media_type="text/event-stream")
from ..auth import CurrentUser, current_user, verify_token
