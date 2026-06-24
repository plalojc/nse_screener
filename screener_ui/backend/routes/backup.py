from __future__ import annotations

import sqlite3
import subprocess
import tempfile
import zipfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path
import os
import shutil
import json
from datetime import date
from typing import Iterable

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from config import DATABASE_URL, DB_PATH, NSE_BHAVCOPY_DB_PATH
from data.db_backend import connect, execute, is_postgres
from ..auth import CurrentUser, USERS_FILE, require_admin
from ..settings import AGENT_ROOT, UI_DB_PATH


router = APIRouter(prefix="/backup")


def _temp_file_response(path: Path, media_type: str, temp_dir: Path) -> FileResponse:
    """Stream a backup file, then delete its temp dir once the response is sent."""
    return FileResponse(
        path,
        media_type=media_type,
        filename=path.name,
        background=BackgroundTask(shutil.rmtree, temp_dir, ignore_errors=True),
    )


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


def _json_safe(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _postgres_json_backup(timestamp: str, temp_dir: Path) -> FileResponse:
    zip_path = temp_dir / f"nse-screener-postgres-json-{timestamp}.zip"
    with connect() as conn, zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as backup_zip:
        tables = execute(conn, """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_type='BASE TABLE'
              AND table_schema NOT IN ('pg_catalog', 'information_schema')
            ORDER BY table_schema, table_name
        """).fetchall()
        manifest = {
            "format": "postgres-json",
            "created_at": datetime.now().isoformat(),
            "tables": [],
        }
        for table in tables:
            schema = str(table["table_schema"])
            table_name = str(table["table_name"])
            qualified = f"{_quote_identifier(schema)}.{_quote_identifier(table_name)}"
            rows = execute(conn, f"SELECT * FROM {qualified}").fetchall()
            payload = [{key: _json_safe(value) for key, value in dict(row).items()} for row in rows]
            archive_name = f"{schema}/{table_name}.json"
            manifest["tables"].append({"schema": schema, "table": table_name, "rows": len(payload), "file": archive_name})
            backup_zip.writestr(archive_name, json.dumps(payload, indent=2, ensure_ascii=False))
        backup_zip.writestr("manifest.json", json.dumps(manifest, indent=2))
    return _temp_file_response(zip_path, "application/zip", temp_dir)


def _postgres_backup(timestamp: str, temp_dir: Path) -> FileResponse:
    if not DATABASE_URL:
        raise HTTPException(status_code=500, detail="DATABASE_URL is not configured.")
    try:
        pg_dump = _pg_dump_path()
    except HTTPException:
        return _postgres_json_backup(timestamp, temp_dir)
    dump_path = temp_dir / f"nse-screener-postgres-{timestamp}.dump"
    result = subprocess.run(
        [pg_dump, "--format=custom", "--no-owner", "--no-acl", f"--file={dump_path}", DATABASE_URL],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "pg_dump failed").strip()
        raise HTTPException(status_code=500, detail=f"Postgres backup failed: {message[:500]}")
    return _temp_file_response(dump_path, "application/octet-stream", temp_dir)


@router.get("")
def download_backup(admin: CurrentUser = Depends(require_admin)) -> FileResponse:
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

    return _temp_file_response(zip_path, "application/zip", temp_dir)
