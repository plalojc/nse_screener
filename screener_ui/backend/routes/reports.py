from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, Response

from ..auth import current_user, require_admin, verify_token
from ..reports import delete_report, list_reports, render_report


router = APIRouter(prefix="/reports")


def _require_report_token(token: str | None):
    if token:
        return verify_token(token, "access")
    raise HTTPException(status_code=401, detail="Login required")


@router.get("")
def reports(user=Depends(current_user)) -> list[dict[str, Any]]:
    return list_reports()


@router.get("/{report_date}/content", response_class=HTMLResponse)
def report_content(report_date: str, kind: str = Query("scan"), token: str | None = None) -> HTMLResponse:
    user = _require_report_token(token)
    if kind != "scan":
        raise HTTPException(status_code=404, detail="Report not found")
    html = render_report(report_date, user.email)
    if not html:
        raise HTTPException(status_code=404, detail="Report not found")
    return HTMLResponse(html)


@router.get("/{report_date}/download")
def report_download(report_date: str, kind: str = Query("scan"), token: str | None = None) -> Response:
    user = _require_report_token(token)
    if kind != "scan":
        raise HTTPException(status_code=404, detail="Report not found")
    html = render_report(report_date, user.email)
    if not html:
        raise HTTPException(status_code=404, detail="Report not found")
    filename = f"NSE-Breakout-{report_date}.html"
    return Response(
        content=html,
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/{report_date}")
def report_delete(report_date: str, kind: str = Query("scan"), admin=Depends(require_admin)) -> dict[str, Any]:
    if kind != "scan":
        raise HTTPException(status_code=404, detail="Report not found")
    deleted = delete_report(report_date)
    if not deleted:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"status": "deleted", "deleted": deleted, "date": report_date}
