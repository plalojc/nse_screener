# ============================================================
# data/nse_bhavcopy_client.py - NSE Bhavcopy data source
# ============================================================
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
import contextlib
import re

import pandas as pd

from config import LOOKBACK_DAYS, NSE_BHAVCOPY_DB_PATH, NSE_BHAVCOPY_DIR
from data.db_backend import (
    bulk_insert_dataframe,
    connect,
    ensure_schemas,
    execute,
    is_postgres,
    read_dataframe,
    system_schema,
    table_name,
)


T_BHAVCOPY_OHLCV = table_name("bhavcopy_ohlcv", system_schema())
T_BHAVCOPY_FILES = table_name("bhavcopy_files", system_schema())


def _get_conn():
    return connect(NSE_BHAVCOPY_DB_PATH)


def init_bhavcopy_db():
    conn = _get_conn()
    ensure_schemas(conn)
    volume_type = "BIGINT" if is_postgres() else "INTEGER"
    execute(conn, f"""
        CREATE TABLE IF NOT EXISTS {T_BHAVCOPY_OHLCV} (
            symbol TEXT NOT NULL,
            date   TEXT NOT NULL,
            open   REAL,
            high   REAL,
            low    REAL,
            close  REAL,
            volume {volume_type},
            PRIMARY KEY (symbol, date)
        )
    """)
    if is_postgres():
        execute(conn, f"ALTER TABLE {T_BHAVCOPY_OHLCV} ALTER COLUMN volume TYPE BIGINT")
    timestamp_default = "TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP" if is_postgres() else "TEXT DEFAULT (datetime('now'))"
    execute(conn, f"""
        CREATE TABLE IF NOT EXISTS {T_BHAVCOPY_FILES} (
            date       TEXT PRIMARY KEY,
            file_path  TEXT,
            status     TEXT NOT NULL,
            row_count  INTEGER DEFAULT 0,
            message    TEXT,
            fetched_at {timestamp_default}
        )
    """)
    if is_postgres():
        execute(conn, f"ALTER TABLE {T_BHAVCOPY_FILES} ADD COLUMN IF NOT EXISTS row_count INTEGER DEFAULT 0")
    else:
        with contextlib.suppress(Exception):
            execute(conn, f"ALTER TABLE {T_BHAVCOPY_FILES} ADD COLUMN row_count INTEGER DEFAULT 0")
    execute(conn, f"CREATE INDEX IF NOT EXISTS idx_bhavcopy_symbol_date ON {T_BHAVCOPY_OHLCV}(symbol, date)")
    rows = execute(
        conn,
        f"SELECT date, message FROM {T_BHAVCOPY_FILES} WHERE COALESCE(row_count, 0)=0 AND status='OK'",
    ).fetchall()
    for row in rows:
        match = re.search(r"(\d+)\s+EQ rows", row["message"] or "")
        if match:
            execute(
                conn,
                f"UPDATE {T_BHAVCOPY_FILES} SET row_count=? WHERE date=?",
                (int(match.group(1)), row["date"]),
            )
    conn.commit()
    conn.close()


def _last_weekday(d: date) -> date:
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _parse_date(value: str | None) -> date:
    if value:
        return _last_weekday(datetime.strptime(value, "%Y-%m-%d").date())
    return _last_weekday(date.today() - timedelta(days=1))


def _weekdays_between(start: date, end: date):
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            yield cur
        cur += timedelta(days=1)


def _is_cached(conn, d: date, target: date | None = None) -> bool:
    row = execute(
        conn,
        f"SELECT status FROM {T_BHAVCOPY_FILES} WHERE date=?",
        (d.isoformat(),),
    ).fetchone()
    if not row:
        return False
    if row["status"] == "OK":
        return True
    # Keep old failed dates cached to avoid retrying every market holiday in the lookback.
    # Always retry the requested target date; it may have failed before NSE published it.
    return row["status"] == "FAILED" and target is not None and d != target


def _record_status(conn, d: date, status: str, file_path: str = "", message: str = "", row_count: int = 0):
    execute(conn, f"""
        INSERT INTO {T_BHAVCOPY_FILES} (date, file_path, status, row_count, message, fetched_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(date) DO UPDATE SET
            file_path=excluded.file_path,
            status=excluded.status,
            row_count=excluded.row_count,
            message=excluded.message,
            fetched_at=excluded.fetched_at
    """, (d.isoformat(), file_path, status, int(row_count or 0), message[:500]))


def _normalise_bhavcopy(df: pd.DataFrame, d: date) -> pd.DataFrame:
    df = df.copy()
    df.columns = df.columns.str.strip()
    series_col = "SERIES" if "SERIES" in df.columns else "SctySrs"
    df = df[df[series_col].astype(str).str.strip() == "EQ"].copy()

    def col(*names: str) -> str:
        for name in names:
            if name in df.columns:
                return name
        raise KeyError(names[0])

    df["symbol"] = df[col("SYMBOL", "TckrSymb")].astype(str).str.strip()
    df["date"] = d.isoformat()
    df["open"] = pd.to_numeric(df[col("OPEN", "OPEN_PRICE", "OpnPric")], errors="coerce")
    df["high"] = pd.to_numeric(df[col("HIGH", "HIGH_PRICE", "HghPric")], errors="coerce")
    df["low"] = pd.to_numeric(df[col("LOW", "LOW_PRICE", "LwPric")], errors="coerce")
    df["close"] = pd.to_numeric(df[col("CLOSE", "CLOSE_PRICE", "ClsPric")], errors="coerce")
    df["volume"] = pd.to_numeric(df[col("TOTTRDQTY", "TTL_TRD_QNTY", "TtlTradgVol")], errors="coerce").fillna(0).astype("int64")
    df = df[["symbol", "date", "open", "high", "low", "close", "volume"]]
    return df.dropna(subset=["symbol", "open", "high", "low", "close"])


def cleanup_bhavcopy_downloads() -> int:
    """Remove temporary Bhavcopy download artifacts after data is stored in DB."""
    out_dir = Path(NSE_BHAVCOPY_DIR)
    if not out_dir.exists():
        return 0
    removed = 0
    for path in out_dir.iterdir():
        if path.is_file() and path.suffix.lower() in {".csv", ".zip"}:
            with contextlib.suppress(OSError):
                path.unlink()
                removed += 1
    return removed


def get_bhavcopy_process_log(days: int = 30) -> pd.DataFrame:
    """Return recent Bhavcopy processing records for audit/debug screens."""
    init_bhavcopy_db()
    conn = _get_conn()
    df = read_dataframe(
        conn,
        f"""
        SELECT date, status, row_count, message, fetched_at
        FROM {T_BHAVCOPY_FILES}
        ORDER BY date DESC
        LIMIT ?
        """,
        params=(days,),
    )
    conn.close()
    return df


def get_bhavcopy_status(scan_date: str) -> dict | None:
    init_bhavcopy_db()
    conn = _get_conn()
    row = execute(
        conn,
        f"""
        SELECT date, status, row_count, message, fetched_at
        FROM {T_BHAVCOPY_FILES}
        WHERE date=?
        """,
        (scan_date,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def _download_and_store(d: date) -> int:
    from jugaad_data.nse import bhavcopy_save

    out_dir = Path(NSE_BHAVCOPY_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = _get_conn()
    file_path: str | Path | None = None
    try:
        file_path = bhavcopy_save(d, str(out_dir))
        df = pd.read_csv(file_path)
        clean = _normalise_bhavcopy(df, d)
        execute(conn, f"DELETE FROM {T_BHAVCOPY_OHLCV} WHERE date=?", (d.isoformat(),))
        bulk_insert_dataframe(
            conn,
            T_BHAVCOPY_OHLCV if is_postgres() else "bhavcopy_ohlcv",
            clean,
            ["symbol", "date", "open", "high", "low", "close", "volume"],
        )
        _record_status(conn, d, "OK", "", f"{len(clean)} EQ rows", row_count=len(clean))
        conn.commit()
        return len(clean)
    except Exception as exc:
        _record_status(conn, d, "FAILED", "", str(exc), row_count=0)
        conn.commit()
        return 0
    finally:
        conn.close()
        if file_path:
            with contextlib.suppress(OSError):
                Path(file_path).unlink()


def update_bhavcopy_cache(scan_date: str | None = None, lookback_days: int = LOOKBACK_DAYS, force_refresh: bool = False) -> str | None:
    """
    Download missing NSE Bhavcopy files into the separate Bhavcopy DB.
    Returns the latest cached trading date available at or before scan_date.
    """
    init_bhavcopy_db()
    target = _parse_date(scan_date)
    start = target - timedelta(days=lookback_days)

    conn = _get_conn()
    missing = [
        d for d in _weekdays_between(start, target) 
        if (force_refresh and d == target) or not _is_cached(conn, d, target)
    ]
    conn.close()

    if missing:
        print(f"[NSE Bhavcopy] Downloading {len(missing)} missing file(s) into {NSE_BHAVCOPY_DB_PATH}...")
    for idx, d in enumerate(missing, 1):
        rows = _download_and_store(d)
        status = f"{rows} EQ rows" if rows else "not available"
        print(f"   [Bhavcopy {idx:>3}/{len(missing)}] {d.isoformat()} -> {status}")
    removed = cleanup_bhavcopy_downloads()
    if removed:
        print(f"   Cleaned {removed} temporary Bhavcopy file(s).")

    return latest_cached_date(target.isoformat())


def latest_cached_date(upto_date: str | None = None) -> str | None:
    init_bhavcopy_db()
    conn = _get_conn()
    if upto_date:
        row = execute(
            conn,
            f"SELECT MAX(date) AS max_date FROM {T_BHAVCOPY_OHLCV} WHERE date<=?",
            (upto_date,),
        ).fetchone()
    else:
        row = execute(conn, f"SELECT MAX(date) AS max_date FROM {T_BHAVCOPY_OHLCV}").fetchone()
    conn.close()
    return row["max_date"] if row and row["max_date"] else None


def fetch_nse_instruments() -> pd.DataFrame:
    """Return the latest EQ universe from cached Bhavcopy data."""
    init_bhavcopy_db()
    latest = latest_cached_date()
    if not latest:
        latest = update_bhavcopy_cache(lookback_days=7)
    if not latest:
        return pd.DataFrame(columns=["symbol", "name", "instrument_key", "lot_size", "isin"])

    conn = _get_conn()
    df = read_dataframe(
        conn,
        f"SELECT DISTINCT symbol FROM {T_BHAVCOPY_OHLCV} WHERE date=? ORDER BY symbol",
        params=(latest,),
    )
    conn.close()
    df["name"] = df["symbol"]
    df["instrument_key"] = df["symbol"]
    df["lot_size"] = 1
    df["isin"] = ""
    return df[["symbol", "name", "instrument_key", "lot_size", "isin"]]


def get_ohlcv_date_map() -> dict:
    init_bhavcopy_db()
    conn = _get_conn()
    rows = execute(
        conn,
        f"SELECT symbol, MAX(date) AS max_date FROM {T_BHAVCOPY_OHLCV} GROUP BY symbol"
    ).fetchall()
    conn.close()
    return {r["symbol"]: r["max_date"] for r in rows}


def load_ohlcv(symbol: str) -> pd.DataFrame:
    init_bhavcopy_db()
    conn = _get_conn()
    df = read_dataframe(
        conn,
        f"SELECT * FROM {T_BHAVCOPY_OHLCV} WHERE symbol=? ORDER BY date",
        params=(symbol,),
    )
    conn.close()
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def load_ohlcv_bulk(symbols: list[str] | None = None, upto_date: str | None = None) -> dict[str, pd.DataFrame]:
    """
    Return cached OHLCV grouped by symbol using one SQLite read.

    The scan loop used to issue one query per symbol. Loading the Bhavcopy
    window once is much faster for the full NSE universe and keeps all
    downstream scanner logic unchanged.
    """
    init_bhavcopy_db()
    params: tuple[str, ...] = ()
    query = f"SELECT * FROM {T_BHAVCOPY_OHLCV}"
    if upto_date:
        query += " WHERE date<=?"
        params = (upto_date,)
    query += " ORDER BY symbol, date"

    conn = _get_conn()
    df = read_dataframe(conn, query, params=params)
    conn.close()

    if df.empty:
        return {}

    if symbols is not None:
        symbol_set = set(symbols)
        df = df[df["symbol"].isin(symbol_set)]
        if df.empty:
            return {}

    df["date"] = pd.to_datetime(df["date"])
    return {
        symbol: group.reset_index(drop=True)
        for symbol, group in df.groupby("symbol", sort=False)
    }


def load_ohlcv_upto(symbol: str, upto_date: str) -> pd.DataFrame:
    init_bhavcopy_db()
    conn = _get_conn()
    df = read_dataframe(
        conn,
        f"SELECT * FROM {T_BHAVCOPY_OHLCV} WHERE symbol=? AND date<=? ORDER BY date",
        params=(symbol, upto_date),
    )
    conn.close()
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def load_ohlcv_range(symbol: str, from_date: str, to_date: str) -> pd.DataFrame:
    init_bhavcopy_db()
    conn = _get_conn()
    df = read_dataframe(
        conn,
        f"SELECT * FROM {T_BHAVCOPY_OHLCV} WHERE symbol=? AND date>? AND date<=? ORDER BY date",
        params=(symbol, from_date, to_date),
    )
    conn.close()
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def get_symbols_with_data_upto(upto_date: str) -> list[str]:
    init_bhavcopy_db()
    conn = _get_conn()
    rows = execute(
        conn,
        f"SELECT DISTINCT symbol FROM {T_BHAVCOPY_OHLCV} WHERE date<=? ORDER BY symbol",
        (upto_date,),
    ).fetchall()
    conn.close()
    return [r["symbol"] for r in rows]


def fetch_historical(symbol: str, scan_date: str | None = None) -> pd.DataFrame:
    """Return cached Bhavcopy OHLCV, downloading missing lookback files first."""
    target = update_bhavcopy_cache(scan_date=scan_date)
    if not target:
        return pd.DataFrame()
    df = load_ohlcv(symbol)
    if df.empty:
        return df
    return df[df["date"] <= pd.to_datetime(target)].reset_index(drop=True)
