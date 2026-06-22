from __future__ import annotations

from typing import Any

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
from .auth import ADMIN_EMAIL
from .store import get_settings, set_setting


SCREENING_MODES = {"confirmed", "pre_breakout", "early_breakout", "both", "best"}

# Admin report-composition percentages: setting key -> config default.
REPORT_PCT_KEYS = {
    "report_pct_breakout": REPORT_PCT_BREAKOUT,
    "report_pct_news": REPORT_PCT_NEWS,
    "report_pct_prebreakout": REPORT_PCT_PREBREAKOUT,
    "report_pct_others": REPORT_PCT_OTHERS,
}


SETTING_DEFAULTS = {
    "tradingview_chart_id": TRADINGVIEW_CHART_ID,
    "llm_validation_limit": str(LLM_VALIDATION_LIMIT),
    "report_include_weak": "true" if REPORT_INCLUDE_WEAK else "false",
    "screening_mode": SCREENING_MODE,
    **{key: str(default) for key, default in REPORT_PCT_KEYS.items()},
}


def _bool_value(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _screening_mode_value(value: str) -> str:
    mode = str(value or "").strip().lower()
    return mode if mode in SCREENING_MODES else "confirmed"


def _pct_value(value: Any, default: int) -> int:
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return default


def app_settings(user_email: str | None = None, is_admin: bool = True) -> dict[str, Any]:
    admin_values = get_settings(SETTING_DEFAULTS, user_email=ADMIN_EMAIL)
    values = get_settings(SETTING_DEFAULTS, user_email=user_email) if user_email else admin_values
    try:
        limit = int(admin_values["llm_validation_limit"])
    except (TypeError, ValueError):
        limit = LLM_VALIDATION_LIMIT
    result = {
        "tradingview_chart_id": values["tradingview_chart_id"],
        "llm_validation_limit": limit,
        "report_include_weak": _bool_value(admin_values["report_include_weak"]),
        "screening_mode": _screening_mode_value(admin_values["screening_mode"]),
        "is_admin": is_admin,
        **{key: _pct_value(admin_values[key], default) for key, default in REPORT_PCT_KEYS.items()},
    }
    if not is_admin:
        result.pop("llm_validation_limit", None)
        result.pop("report_include_weak", None)
        result.pop("screening_mode", None)
        for key in REPORT_PCT_KEYS:
            result.pop(key, None)
    return result


def save_app_settings(
    tradingview_chart_id: str,
    llm_validation_limit: int,
    report_include_weak: bool,
    user_email: str | None = None,
    is_admin: bool = True,
    screening_mode: str | None = None,
    report_pcts: dict[str, int] | None = None,
) -> dict[str, Any]:
    set_setting("tradingview_chart_id", tradingview_chart_id.strip(), user_email=user_email)
    if is_admin:
        set_setting("llm_validation_limit", str(llm_validation_limit), user_email=ADMIN_EMAIL)
        set_setting("report_include_weak", "true" if report_include_weak else "false", user_email=ADMIN_EMAIL)
        if screening_mode is not None:
            set_setting("screening_mode", _screening_mode_value(screening_mode), user_email=ADMIN_EMAIL)
        for key, default in REPORT_PCT_KEYS.items():
            if report_pcts and key in report_pcts:
                set_setting(key, str(_pct_value(report_pcts[key], default)), user_email=ADMIN_EMAIL)
    return app_settings(user_email=user_email, is_admin=is_admin)
