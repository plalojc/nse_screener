from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends

from ..auth import CurrentUser, current_user, public_users
from ..reports import list_reports
from ..runtime import jobs, scheduler_state
from ..store import list_holdings, list_watchlist, profit_loss_report
from ..user_settings import app_settings


router = APIRouter()


def _month_start_today() -> tuple[str, str]:
    today = date.today()
    return today.replace(day=1).isoformat(), today.isoformat()


@router.get("/bootstrap")
def bootstrap(user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    reports = list_reports()
    latest_job = jobs.latest()
    from_date, to_date = _month_start_today()
    watchlist = list_watchlist(user.email)
    holdings = list_holdings(user.email)
    invested = round(sum(float(row["invested_amount"] or 0) for row in holdings), 2)
    current_rows = [row for row in holdings if row.get("current_value") is not None]
    current = round(sum(float(row["current_value"] or 0) for row in current_rows), 2)
    pnl = round(current - invested, 2) if current_rows else None
    pnl_pct = round(pnl / invested * 100, 2) if pnl is not None and invested else None
    holdings_totals = {
        "count": len(holdings),
        "invested_amount": invested,
        "current_value": current if current_rows else None,
        "profit_loss": pnl,
        "profit_loss_pct": pnl_pct,
        "as_of": date.today().isoformat(),
    }

    payload = {
        "dashboard": {
            "latest_report": reports[0] if reports else None,
            "latest_job": latest_job.snapshot() if latest_job else None,
            "reports_count": len(reports),
            "watchlist_count": len(watchlist),
            "holdings": holdings_totals,
            "is_admin": user.is_admin,
            "scheduler": scheduler_state(),
        },
        "reports": reports,
        "watchlist": watchlist,
        "holdings": holdings,
        "settings": app_settings(user.email, is_admin=user.is_admin),
        "profitLoss": {
            "from_date": from_date,
            "to_date": to_date,
            "data": profit_loss_report(user.email, from_date, to_date),
        },
    }
    if user.is_admin:
        payload["users"] = public_users()
    return payload
