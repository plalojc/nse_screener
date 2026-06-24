from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from ..auth import AUTH_SECRET, current_user, require_admin
from ..runtime import run_due_schedule_check, scheduler_state, update_scheduler


router = APIRouter(prefix="/scheduler")


class SchedulerRequest(BaseModel):
    enabled: bool
    time: str


@router.get("")
def get_scheduler(user=Depends(current_user)) -> dict[str, Any]:
    return scheduler_state()


@router.put("")
def set_scheduler(payload: SchedulerRequest, user=Depends(require_admin)) -> dict[str, Any]:
    parts = payload.time.split(":", 1)
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail="Time must be HH:MM")
    try:
        hour, minute = [int(part) for part in parts]
    except ValueError:
        raise HTTPException(status_code=400, detail="Time must be HH:MM") from None
    if hour > 23 or minute > 59:
        raise HTTPException(status_code=400, detail="Time must be HH:MM")
    return update_scheduler(payload.enabled, payload.time)


@router.post("/tick")
def scheduler_tick(x_scheduler_token: str | None = Header(default=None)) -> dict[str, Any]:
    """Internal endpoint hit by the Cloudflare cron trigger to wake the container
    and run the daily scan if due. Token-protected (shared SCREENER_JWT_SECRET);
    blocks until the scan finishes so the container stays alive for the run."""
    if not x_scheduler_token or not hmac.compare_digest(x_scheduler_token, AUTH_SECRET):
        raise HTTPException(status_code=403, detail="Forbidden")
    result = run_due_schedule_check(block=True)
    from ..reports import list_reports, render_report

    # Full report list (DB = source of truth) so the Worker can refresh its R2
    # index.json — this is how OLD reports get listed, not just freshly cached ones.
    result["reports"] = list_reports()
    # Return the rendered report so the Worker can cache it in R2 (served to
    # users without waking the container). Uses admin settings (no user scope).
    if result.get("status") == "success" and result.get("report_date"):
        html = render_report(result["report_date"])
        if html:
            result["report_html"] = html
    return result
