from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse

from ..reports import find_report, list_reports


router = APIRouter(prefix="/reports")


@router.get("")
def reports() -> list[dict[str, Any]]:
    return list_reports()


@router.get("/{report_date}/content", response_class=HTMLResponse)
def report_content(report_date: str, kind: str = Query("scan")) -> HTMLResponse:
    path = find_report(report_date, kind=kind)
    if not path:
        raise HTTPException(status_code=404, detail="Report not found")
    return HTMLResponse(path.read_text(encoding="utf-8", errors="replace"))


@router.get("/{report_date}/download")
def report_download(report_date: str, kind: str = Query("scan")) -> FileResponse:
    path = find_report(report_date, kind=kind)
    if not path:
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(path, filename=path.name, media_type="text/html")
