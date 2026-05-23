from __future__ import annotations

from typing import Any

from config import LLM_VALIDATION_LIMIT, REPORT_INCLUDE_WEAK, TRADINGVIEW_CHART_ID
from .store import get_settings, set_setting


SETTING_DEFAULTS = {
    "tradingview_chart_id": TRADINGVIEW_CHART_ID,
    "llm_validation_limit": str(LLM_VALIDATION_LIMIT),
    "report_include_weak": "true" if REPORT_INCLUDE_WEAK else "false",
}


def _bool_value(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def app_settings() -> dict[str, Any]:
    values = get_settings(SETTING_DEFAULTS)
    try:
        limit = int(values["llm_validation_limit"])
    except (TypeError, ValueError):
        limit = LLM_VALIDATION_LIMIT
    return {
        "tradingview_chart_id": values["tradingview_chart_id"],
        "llm_validation_limit": limit,
        "report_include_weak": _bool_value(values["report_include_weak"]),
    }


def save_app_settings(
    tradingview_chart_id: str,
    llm_validation_limit: int,
    report_include_weak: bool,
) -> dict[str, Any]:
    set_setting("tradingview_chart_id", tradingview_chart_id.strip())
    set_setting("llm_validation_limit", str(llm_validation_limit))
    set_setting("report_include_weak", "true" if report_include_weak else "false")
    return app_settings()
