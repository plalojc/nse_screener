from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..reports import list_reports
from ..runtime import jobs, scheduler_state
from ..settings import AGENT_ROOT
from ..store import holdings_summary, list_watchlist


router = APIRouter()


@router.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "agent_root": str(AGENT_ROOT)}


@router.get("/dashboard")
def dashboard() -> dict[str, Any]:
    reports = list_reports()
    latest_job = jobs.latest()
    return {
        "latest_report": reports[0] if reports else None,
        "latest_job": latest_job.snapshot() if latest_job else None,
        "reports_count": len(reports),
        "watchlist_count": len(list_watchlist()),
        "holdings": holdings_summary(),
        "scheduler": scheduler_state(),
    }
