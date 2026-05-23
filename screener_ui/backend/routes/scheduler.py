from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..runtime import scheduler_state, update_scheduler


router = APIRouter(prefix="/scheduler")


class SchedulerRequest(BaseModel):
    enabled: bool
    time: str


@router.get("")
def get_scheduler() -> dict[str, Any]:
    return scheduler_state()


@router.put("")
def set_scheduler(payload: SchedulerRequest) -> dict[str, Any]:
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
