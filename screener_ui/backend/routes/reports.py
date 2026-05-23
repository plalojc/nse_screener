from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, Response

from ..reports import delete_report, list_reports, render_report


router = APIRouter(prefix="/reports")


@router.get("")
def reports() -> list[dict[str, Any]]:
    return list_reports()


@router.get("/{report_date}/content", response_class=HTMLResponse)
def report_content(report_date: str, kind: str = Query("scan")) -> HTMLResponse:
    if kind != "scan":
        raise HTTPException(status_code=404, detail="Report not found")
    html = render_report(report_date)
    if not html:
        raise HTTPException(status_code=404, detail="Report not found")
    return HTMLResponse(html)


@router.get("/{report_date}/download")
def report_download(report_date: str, kind: str = Query("scan")) -> Response:
    if kind != "scan":
        raise HTTPException(status_code=404, detail="Report not found")
    html = render_report(report_date)
    if not html:
        raise HTTPException(status_code=404, detail="Report not found")
    filename = f"NSE-Breakout-{report_date}.html"
    return Response(
        content=html,
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/{report_date}")
def report_delete(report_date: str, kind: str = Query("scan")) -> dict[str, Any]:
    if kind != "scan":
        raise HTTPException(status_code=404, detail="Report not found")
    deleted = delete_report(report_date)
    if not deleted:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"status": "deleted", "deleted": deleted, "date": report_date}
