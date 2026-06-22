from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import (
    LLM_VALIDATION_LIMIT,
    REPORT_INCLUDE_WEAK,
    REPORT_PCT_BREAKOUT,
    REPORT_PCT_NEWS,
    REPORT_PCT_OTHERS,
    REPORT_PCT_PREBREAKOUT,
    SCREENING_MODE,
    TRADINGVIEW_CHART_ID,
)
from ..auth import CurrentUser, current_user
from ..user_settings import SCREENING_MODES, app_settings, save_app_settings


router = APIRouter(prefix="/settings")


class SettingsRequest(BaseModel):
    tradingview_chart_id: str = Field(default=TRADINGVIEW_CHART_ID, max_length=80)
    llm_validation_limit: int = Field(default=LLM_VALIDATION_LIMIT, ge=0, le=1000)
    report_include_weak: bool = REPORT_INCLUDE_WEAK
    screening_mode: str = Field(default=SCREENING_MODE, max_length=20)
    report_pct_breakout: int = Field(default=REPORT_PCT_BREAKOUT, ge=0, le=100)
    report_pct_news: int = Field(default=REPORT_PCT_NEWS, ge=0, le=100)
    report_pct_prebreakout: int = Field(default=REPORT_PCT_PREBREAKOUT, ge=0, le=100)
    report_pct_others: int = Field(default=REPORT_PCT_OTHERS, ge=0, le=100)

@router.get("")
def get_app_settings(user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    return app_settings(user.email, is_admin=user.is_admin)


@router.put("")
def update_app_settings(payload: SettingsRequest, user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    chart_id = payload.tradingview_chart_id.strip()
    if "/" in chart_id or "?" in chart_id:
        raise HTTPException(status_code=400, detail="Enter only the TradingView chart id, not the full URL")

    screening_mode = payload.screening_mode.strip().lower()
    if screening_mode not in SCREENING_MODES:
        raise HTTPException(status_code=400, detail=f"screening_mode must be one of {sorted(SCREENING_MODES)}")

    report_pcts = {
        "report_pct_breakout": payload.report_pct_breakout,
        "report_pct_news": payload.report_pct_news,
        "report_pct_prebreakout": payload.report_pct_prebreakout,
        "report_pct_others": payload.report_pct_others,
    }
    if sum(report_pcts.values()) == 0:
        raise HTTPException(status_code=400, detail="At least one report category percentage must be greater than 0")

    return save_app_settings(
        chart_id,
        payload.llm_validation_limit,
        payload.report_include_weak,
        user.email,
        user.is_admin,
        screening_mode=screening_mode,
        report_pcts=report_pcts,
    )
