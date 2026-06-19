from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import LLM_VALIDATION_LIMIT, REPORT_INCLUDE_WEAK, TRADINGVIEW_CHART_ID
from ..auth import CurrentUser, current_user
from ..user_settings import app_settings, save_app_settings


router = APIRouter(prefix="/settings")


class SettingsRequest(BaseModel):
    tradingview_chart_id: str = Field(default=TRADINGVIEW_CHART_ID, max_length=80)
    llm_validation_limit: int = Field(default=LLM_VALIDATION_LIMIT, ge=0, le=1000)
    report_include_weak: bool = REPORT_INCLUDE_WEAK

@router.get("")
def get_app_settings(user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    return app_settings(user.email, is_admin=user.is_admin)


@router.put("")
def update_app_settings(payload: SettingsRequest, user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    chart_id = payload.tradingview_chart_id.strip()
    if "/" in chart_id or "?" in chart_id:
        raise HTTPException(status_code=400, detail="Enter only the TradingView chart id, not the full URL")

    return save_app_settings(
        chart_id,
        payload.llm_validation_limit,
        payload.report_include_weak,
        user.email,
        user.is_admin,
    )
