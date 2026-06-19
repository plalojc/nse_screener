from __future__ import annotations

from typing import Any

from config import LLM_VALIDATION_LIMIT, REPORT_INCLUDE_WEAK, TRADINGVIEW_CHART_ID
from .auth import ADMIN_EMAIL
from .store import get_settings, set_setting


SETTING_DEFAULTS = {
    "tradingview_chart_id": TRADINGVIEW_CHART_ID,
    "llm_validation_limit": str(LLM_VALIDATION_LIMIT),
    "report_include_weak": "true" if REPORT_INCLUDE_WEAK else "false",
}


def _bool_value(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


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
        "is_admin": is_admin,
    }
    if not is_admin:
        result.pop("llm_validation_limit", None)
        result.pop("report_include_weak", None)
    return result


def save_app_settings(
    tradingview_chart_id: str,
    llm_validation_limit: int,
    report_include_weak: bool,
    user_email: str | None = None,
    is_admin: bool = True,
) -> dict[str, Any]:
    set_setting("tradingview_chart_id", tradingview_chart_id.strip(), user_email=user_email)
    if is_admin:
        set_setting("llm_validation_limit", str(llm_validation_limit), user_email=ADMIN_EMAIL)
        set_setting("report_include_weak", "true" if report_include_weak else "false", user_email=ADMIN_EMAIL)
    return app_settings(user_email=user_email, is_admin=is_admin)
