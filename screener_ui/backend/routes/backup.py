from __future__ import annotations

import sqlite3
import subprocess
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
import os
import shutil
from typing import Iterable

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from config import DATABASE_URL, DB_PATH, NSE_BHAVCOPY_DB_PATH
from data.db_backend import is_postgres
from ..auth import USERS_FILE, verify_token
from ..settings import AGENT_ROOT, UI_DB_PATH


router = APIRouter(prefix="/backup")


def _snapshot_sqlite(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(src) as source, sqlite3.connect(dst) as target:
        source.backup(target)


def _existing_files() -> Iterable[tuple[str, Path, bool]]:
    yield "nse_agent.db", (AGENT_ROOT / DB_PATH).resolve(), True
    yield "nse_bhavcopy.db", (AGENT_ROOT / NSE_BHAVCOPY_DB_PATH).resolve(), True
    yield "ui_state.db", UI_DB_PATH.resolve(), True
    yield "users.json", USERS_FILE.resolve(), False


def _pg_dump_path() -> str:
    configured = os.getenv("PG_DUMP_PATH", "").strip()
    if configured:
        return configured
    found = shutil.which("pg_dump")
    if found:
        return found
    raise HTTPException(
        status_code=500,
        detail="Postgres backup requires pg_dump on the server. Install PostgreSQL client tools or set PG_DUMP_PATH.",
    )


def _postgres_backup(timestamp: str, temp_dir: Path) -> FileResponse:
    if not DATABASE_URL:
        raise HTTPException(status_code=500, detail="DATABASE_URL is not configured.")
    dump_path = temp_dir / f"nse-screener-postgres-{timestamp}.dump"
    result = subprocess.run(
        [_pg_dump_path(), "--format=custom", "--no-owner", "--no-acl", f"--file={dump_path}", DATABASE_URL],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "pg_dump failed").strip()
        raise HTTPException(status_code=500, detail=f"Postgres backup failed: {message[:500]}")
    return FileResponse(
        dump_path,
        media_type="application/octet-stream",
        filename=dump_path.name,
    )


@router.get("")
def download_backup(token: str | None = Query(default=None)) -> FileResponse:
    admin = verify_token(token or "", "access")
    if not admin.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    temp_dir = Path(tempfile.mkdtemp(prefix="nse-screener-backup-"))
    if is_postgres():
        return _postgres_backup(timestamp, temp_dir)

    zip_path = temp_dir / f"nse-screener-backup-{timestamp}.zip"

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as backup_zip:
        for archive_name, source_path, is_sqlite in _existing_files():
            if not source_path.exists():
                continue
            if is_sqlite:
                snapshot_path = temp_dir / archive_name
                _snapshot_sqlite(source_path, snapshot_path)
                backup_zip.write(snapshot_path, archive_name)
            else:
                backup_zip.write(source_path, archive_name)

    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=zip_path.name,
    )
