# ============================================================
# data/nse_bhavcopy_client.py - NSE Bhavcopy data source
# ============================================================
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from config import LOOKBACK_DAYS, NSE_BHAVCOPY_DB_PATH, NSE_BHAVCOPY_DIR


def _get_conn():
    conn = sqlite3.connect(NSE_BHAVCOPY_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_bhavcopy_db():
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bhavcopy_ohlcv (
            symbol TEXT NOT NULL,
            date   TEXT NOT NULL,
            open   REAL,
            high   REAL,
            low    REAL,
            close  REAL,
            volume INTEGER,
            PRIMARY KEY (symbol, date)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bhavcopy_files (
            date       TEXT PRIMARY KEY,
            file_path  TEXT,
            status     TEXT NOT NULL,
            message    TEXT,
            fetched_at TEXT DEFAULT (datetime('now'))
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bhavcopy_symbol_date ON bhavcopy_ohlcv(symbol, date)")
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


def _is_cached(conn, d: date) -> bool:
    row = conn.execute(
        "SELECT status FROM bhavcopy_files WHERE date=?",
        (d.isoformat(),),
    ).fetchone()
    # Accept both OK and FAILED as 'already processed' to prevent infinite holiday loops
    return bool(row and row["status"] in ("OK", "FAILED"))


def _record_status(conn, d: date, status: str, file_path: str = "", message: str = ""):
    conn.execute("""
        INSERT INTO bhavcopy_files (date, file_path, status, message, fetched_at)
        VALUES (?, ?, ?, ?, datetime('now'))
        ON CONFLICT(date) DO UPDATE SET
            file_path=excluded.file_path,
            status=excluded.status,
            message=excluded.message,
            fetched_at=excluded.fetched_at
    """, (d.isoformat(), file_path, status, message[:500]))


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


def _download_and_store(d: date) -> int:
    from jugaad_data.nse import bhavcopy_save

    out_dir = Path(NSE_BHAVCOPY_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = _get_conn()
    try:
        file_path = bhavcopy_save(d, str(out_dir))
        df = pd.read_csv(file_path)
        clean = _normalise_bhavcopy(df, d)
        conn.execute("DELETE FROM bhavcopy_ohlcv WHERE date=?", (d.isoformat(),))
        clean.to_sql("bhavcopy_ohlcv", conn, if_exists="append", index=False, method="multi")
        _record_status(conn, d, "OK", str(file_path), f"{len(clean)} EQ rows")
        conn.commit()
        return len(clean)
    except Exception as exc:
        _record_status(conn, d, "FAILED", "", str(exc))
        conn.commit()
        return 0
    finally:
        conn.close()


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
        if (force_refresh and d == target) or not _is_cached(conn, d)
    ]
    conn.close()

    if missing:
        print(f"[NSE Bhavcopy] Downloading {len(missing)} missing file(s) into {NSE_BHAVCOPY_DB_PATH}...")
    for idx, d in enumerate(missing, 1):
        rows = _download_and_store(d)
        status = f"{rows} EQ rows" if rows else "not available"
        print(f"   [Bhavcopy {idx:>3}/{len(missing)}] {d.isoformat()} -> {status}")

    return latest_cached_date(target.isoformat())


def latest_cached_date(upto_date: str | None = None) -> str | None:
    init_bhavcopy_db()
    conn = _get_conn()
    if upto_date:
        row = conn.execute(
            "SELECT MAX(date) AS max_date FROM bhavcopy_ohlcv WHERE date<=?",
            (upto_date,),
        ).fetchone()
    else:
        row = conn.execute("SELECT MAX(date) AS max_date FROM bhavcopy_ohlcv").fetchone()
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
    df = pd.read_sql(
        "SELECT DISTINCT symbol FROM bhavcopy_ohlcv WHERE date=? ORDER BY symbol",
        conn,
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
    rows = conn.execute(
        "SELECT symbol, MAX(date) AS max_date FROM bhavcopy_ohlcv GROUP BY symbol"
    ).fetchall()
    conn.close()
    return {r["symbol"]: r["max_date"] for r in rows}


def load_ohlcv(symbol: str) -> pd.DataFrame:
    init_bhavcopy_db()
    conn = _get_conn()
    df = pd.read_sql(
        "SELECT * FROM bhavcopy_ohlcv WHERE symbol=? ORDER BY date",
        conn,
        params=(symbol,),
    )
    conn.close()
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def load_ohlcv_upto(symbol: str, upto_date: str) -> pd.DataFrame:
    init_bhavcopy_db()
    conn = _get_conn()
    df = pd.read_sql(
        "SELECT * FROM bhavcopy_ohlcv WHERE symbol=? AND date<=? ORDER BY date",
        conn,
        params=(symbol, upto_date),
    )
    conn.close()
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def load_ohlcv_range(symbol: str, from_date: str, to_date: str) -> pd.DataFrame:
    init_bhavcopy_db()
    conn = _get_conn()
    df = pd.read_sql(
        "SELECT * FROM bhavcopy_ohlcv WHERE symbol=? AND date>? AND date<=? ORDER BY date",
        conn,
        params=(symbol, from_date, to_date),
    )
    conn.close()
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def get_symbols_with_data_upto(upto_date: str) -> list[str]:
    init_bhavcopy_db()
    conn = _get_conn()
    rows = conn.execute(
        "SELECT DISTINCT symbol FROM bhavcopy_ohlcv WHERE date<=? ORDER BY symbol",
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
