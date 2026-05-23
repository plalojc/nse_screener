from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..reports import report_exists
from ..runtime import jobs
from ..scanner_runner import sse_event


router = APIRouter(prefix="/scan")


class ScanRequest(BaseModel):
    scan_date: str | None = None
    force_refresh: bool = False


@router.post("/run")
def run_scan(payload: ScanRequest) -> dict[str, Any]:
    if payload.scan_date and report_exists(payload.scan_date):
        return {
            "id": None,
            "status": "skipped",
            "progress": 100,
            "message": f"Report already exists for {payload.scan_date}. Delete that report before running the scan again.",
            "started_at": None,
            "ended_at": None,
            "exit_code": 0,
            "lines": [
                f"Report already exists for {payload.scan_date}.",
                "Delete the existing report from Reports page before running this scan again.",
            ],
            "command": [],
            "existing_report": {
                "date": payload.scan_date,
                "kind": "scan",
                "filename": f"NSE-Breakout-{payload.scan_date}.html",
            },
        }
    job = jobs.start_scan(scan_date=payload.scan_date, force_refresh=payload.force_refresh)
    return job.snapshot()


@router.get("/jobs")
def scan_jobs() -> list[dict[str, Any]]:
    return jobs.list_jobs()


@router.get("/jobs/{job_id}")
def scan_job(job_id: str) -> dict[str, Any]:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Scan job not found")
    return job.snapshot()


@router.get("/jobs/{job_id}/events")
async def scan_events(job_id: str) -> StreamingResponse:
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
