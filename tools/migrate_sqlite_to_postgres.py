from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.database import init_db
from data.db_backend import connect, execute, executemany, is_postgres, system_schema, table_name, user_schema
from data.nse_bhavcopy_client import init_bhavcopy_db
from screener_ui.backend.store import init_store


AGENT_DB = ROOT / "nse_agent.db"
BHAVCOPY_DB = ROOT / "nse_bhavcopy.db"
UI_DB = ROOT / "screener_ui" / "backend" / "ui_state.db"


TABLES = [
    {
        "source_db": AGENT_DB,
        "source_table": "signals",
        "target_table": table_name("signals", user_schema()),
        "columns": ["symbol", "signal_date", "signal_type", "price", "reason", "created_at"],
        "conflict": None,
    },
    {
        "source_db": AGENT_DB,
        "source_table": "positions",
        "target_table": table_name("positions", user_schema()),
        "columns": [
            "symbol", "buy_date", "buy_price", "quantity", "target_price",
            "stop_loss_price", "trailing_stop_price", "status", "exit_price",
            "exit_date", "pnl_pct",
        ],
        "conflict": "(symbol) DO NOTHING",
    },
    {
        "source_db": AGENT_DB,
        "source_table": "breakout_log",
        "target_table": table_name("breakout_log", system_schema()),
        "columns": [
            "scan_date", "symbol", "signal_type", "close", "rsi", "vol_ratio",
            "score", "stage", "ema20", "ema50", "atr14", "swing_low", "reasons",
            "llm_verdict", "llm_confidence", "llm_reasoning", "llm_model",
            "panel_method", "vcp_detected", "bull_flag_detected", "pattern_score",
            "created_at",
        ],
        "conflict": "(scan_date, symbol) DO NOTHING",
    },
    {
        "source_db": AGENT_DB,
        "source_table": "llm_evaluations",
        "target_table": table_name("llm_evaluations", system_schema()),
        "columns": [
            "scan_date", "symbol", "panel_method", "llm_model", "verdict",
            "confidence", "reasoning", "created_at", "updated_at",
        ],
        "conflict": "(scan_date, symbol, panel_method, llm_model) DO NOTHING",
    },
    {
        "source_db": AGENT_DB,
        "source_table": "catalyst_events",
        "target_table": table_name("catalyst_events", system_schema()),
        "columns": [
            "event_date", "symbol", "source", "category", "title", "summary",
            "url", "score", "confidence", "theme", "mapping_source",
            "raw_payload", "fetched_at",
        ],
        "conflict": "(event_date, symbol, source, title) DO NOTHING",
    },
    {
        "source_db": AGENT_DB,
        "source_table": "invalid_instruments",
        "target_table": table_name("invalid_instruments", system_schema()),
        "columns": ["symbol", "reason", "source", "added_at"],
        "conflict": "(symbol) DO NOTHING",
    },
    {
        "source_db": BHAVCOPY_DB,
        "source_table": "bhavcopy_files",
        "target_table": table_name("bhavcopy_files", system_schema()),
        "columns": ["date", "file_path", "status", "message", "fetched_at"],
        "conflict": "(date) DO NOTHING",
    },
    {
        "source_db": BHAVCOPY_DB,
        "source_table": "bhavcopy_ohlcv",
        "target_table": table_name("bhavcopy_ohlcv", system_schema()),
        "columns": ["symbol", "date", "open", "high", "low", "close", "volume"],
        "conflict": "(symbol, date) DO NOTHING",
    },
    {
        "source_db": UI_DB,
        "source_table": "watchlist",
        "target_table": table_name("watchlist", user_schema()),
        "columns": ["symbol", "notes", "target_price", "created_at", "updated_at"],
        "conflict": "(symbol) DO NOTHING",
    },
    {
        "source_db": UI_DB,
        "source_table": "holdings",
        "target_table": table_name("holdings", user_schema()),
        "columns": ["symbol", "buy_date", "quantity", "buy_price", "invested_amount", "notes", "created_at", "updated_at"],
        "conflict": None,
    },
    {
        "source_db": UI_DB,
        "source_table": "holding_sales",
        "target_table": table_name("holding_sales", user_schema()),
        "columns": [
            "holding_id", "symbol", "sell_date", "quantity", "sell_price",
            "sell_amount", "realized_profit_loss", "notes", "created_at",
        ],
        "conflict": None,
    },
    {
        "source_db": UI_DB,
        "source_table": "ui_settings",
        "target_table": table_name("ui_settings", user_schema()),
        "columns": ["key", "value", "updated_at"],
        "conflict": "(key) DO NOTHING",
    },
]


def source_table_exists(db_path: Path, table: str) -> bool:
    if not db_path.exists():
        return False
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
    return bool(row)


def source_rows(db_path: Path, table: str, columns: list[str]) -> list[tuple]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        existing_cols = {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        selected = [col for col in columns if col in existing_cols]
        if not selected:
            return []
        sql = f"SELECT {', '.join(selected)} FROM {table}"
        rows = conn.execute(sql).fetchall()
    return [tuple(row[col] for col in selected) for row in rows], selected


def migrate_table(spec: dict, replace: bool) -> int:
    source_db = Path(spec["source_db"])
    source_table = spec["source_table"]
    target_table = spec["target_table"]
    if not source_table_exists(source_db, source_table):
        print(f"[skip] {source_table}: source not found at {source_db}")
        return 0

    rows, columns = source_rows(source_db, source_table, spec["columns"])
    if not rows:
        print(f"[skip] {source_table}: no rows")
        return 0

    placeholders = ", ".join(["?"] * len(columns))
    column_sql = ", ".join(columns)
    conflict = spec.get("conflict")
    if replace:
        with connect() as conn:
            execute(conn, f"DELETE FROM {target_table}")
            conn.commit()
        conflict = None

    sql = f"INSERT INTO {target_table} ({column_sql}) VALUES ({placeholders})"
    if conflict:
        sql += f" ON CONFLICT {conflict}"

    with connect() as conn:
        executemany(conn, sql, rows)
        conn.commit()
    print(f"[ok] {source_table}: migrated {len(rows)} row(s)")
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Copy local SQLite runtime data into Postgres.")
    parser.add_argument("--replace", action="store_true", help="Delete target table rows before copying.")
    args = parser.parse_args()

    if not is_postgres():
        raise SystemExit("Set DATABASE_URL or DB_BACKEND=postgres before running this migration.")

    init_db()
    init_bhavcopy_db()
    init_store()
    total = 0
    for spec in TABLES:
        total += migrate_table(spec, args.replace)
    print(f"Done. Migrated {total} row(s).")


if __name__ == "__main__":
    main()
