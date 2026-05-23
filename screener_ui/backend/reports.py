from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .settings import REPORTS_DIR


REPORT_RE = re.compile(r"^(?P<kind>NSE-Breakout|NSE-Backtest)-(?P<date>\d{4}-\d{2}-\d{2}).*\.html$")


def list_reports() -> list[dict[str, Any]]:
    if not REPORTS_DIR.exists():
        return []
    reports = []
    for path in REPORTS_DIR.glob("*.html"):
        match = REPORT_RE.match(path.name)
        if not match:
            continue
        stat = path.stat()
        reports.append({
            "date": match.group("date"),
            "kind": "scan" if match.group("kind") == "NSE-Breakout" else "backtest",
            "filename": path.name,
            "size": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        })
    reports.sort(key=lambda item: (item["date"], item["modified_at"]), reverse=True)
    return reports


def find_report(report_date: str, kind: str = "scan") -> Path | None:
    prefix = "NSE-Breakout" if kind == "scan" else "NSE-Backtest"
    candidates = sorted(
        REPORTS_DIR.glob(f"{prefix}-{report_date}*.html"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None
