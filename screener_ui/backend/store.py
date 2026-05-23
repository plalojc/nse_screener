from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from .settings import BHAVCOPY_DB_PATH, UI_DB_PATH


def _connect(path: Path = UI_DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_store() -> None:
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL UNIQUE,
                notes TEXT,
                target_price REAL,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS holdings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                buy_date TEXT NOT NULL,
                quantity REAL NOT NULL,
                buy_price REAL NOT NULL,
                invested_amount REAL NOT NULL,
                notes TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ui_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def add_watchlist(symbol: str, notes: str = "", target_price: float | None = None) -> dict:
    symbol = symbol.strip().upper()
    with _connect() as conn:
        conn.execute("""
            INSERT INTO watchlist (symbol, notes, target_price, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(symbol) DO UPDATE SET
                notes=excluded.notes,
                target_price=excluded.target_price,
                updated_at=datetime('now')
        """, (symbol, notes.strip(), target_price))
        row = conn.execute("SELECT * FROM watchlist WHERE symbol=?", (symbol,)).fetchone()
    return _row_to_dict(row) or {}


def list_watchlist() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM watchlist ORDER BY updated_at DESC, symbol").fetchall()
    return [dict(row) for row in rows]


def delete_watchlist(item_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM watchlist WHERE id=?", (item_id,))


def add_holding(
    symbol: str,
    buy_date: str,
    quantity: float,
    buy_price: float,
    notes: str = "",
) -> dict:
    symbol = symbol.strip().upper()
    invested = round(float(quantity) * float(buy_price), 2)
    with _connect() as conn:
        cur = conn.execute("""
            INSERT INTO holdings
                (symbol, buy_date, quantity, buy_price, invested_amount, notes, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
        """, (symbol, buy_date, quantity, buy_price, invested, notes.strip()))
        row = conn.execute("SELECT * FROM holdings WHERE id=?", (cur.lastrowid,)).fetchone()
    return enrich_holding(_row_to_dict(row) or {})


def update_holding(item_id: int, payload: dict[str, Any]) -> dict | None:
    existing = get_holding(item_id)
    if not existing:
        return None
    symbol = str(payload.get("symbol", existing["symbol"])).strip().upper()
    buy_date = str(payload.get("buy_date", existing["buy_date"]))
    quantity = float(payload.get("quantity", existing["quantity"]))
    buy_price = float(payload.get("buy_price", existing["buy_price"]))
    notes = str(payload.get("notes", existing.get("notes") or "")).strip()
    invested = round(quantity * buy_price, 2)

    with _connect() as conn:
        conn.execute("""
            UPDATE holdings
            SET symbol=?, buy_date=?, quantity=?, buy_price=?,
                invested_amount=?, notes=?, updated_at=datetime('now')
            WHERE id=?
        """, (symbol, buy_date, quantity, buy_price, invested, notes, item_id))
        row = conn.execute("SELECT * FROM holdings WHERE id=?", (item_id,)).fetchone()
    return enrich_holding(_row_to_dict(row) or {})


def get_holding(item_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM holdings WHERE id=?", (item_id,)).fetchone()
    return _row_to_dict(row)


def list_holdings() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM holdings ORDER BY buy_date DESC, id DESC").fetchall()
    return [enrich_holding(dict(row)) for row in rows]


def delete_holding(item_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM holdings WHERE id=?", (item_id,))


def set_setting(key: str, value: str) -> None:
    with _connect() as conn:
        conn.execute("""
            INSERT INTO ui_settings (key, value, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET
                value=excluded.value,
                updated_at=datetime('now')
        """, (key, value))


def get_setting(key: str, default: str = "") -> str:
    with _connect() as conn:
        row = conn.execute("SELECT value FROM ui_settings WHERE key=?", (key,)).fetchone()
    return str(row["value"]) if row else default


def latest_prices(symbols: list[str] | None = None) -> dict[str, dict[str, Any]]:
    if not BHAVCOPY_DB_PATH.exists():
        return {}
    params: tuple[Any, ...] = ()
    where = ""
    if symbols:
        placeholders = ",".join("?" for _ in symbols)
        where = f"WHERE symbol IN ({placeholders})"
        params = tuple(symbols)

    sql = f"""
        WITH latest AS (
            SELECT symbol, MAX(date) AS max_date
            FROM bhavcopy_ohlcv
            {where}
            GROUP BY symbol
        )
        SELECT b.symbol, b.date, b.close
        FROM bhavcopy_ohlcv b
        JOIN latest l ON l.symbol=b.symbol AND l.max_date=b.date
    """
    try:
        conn = sqlite3.connect(BHAVCOPY_DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
        conn.close()
    except sqlite3.Error:
        return {}
    return {row["symbol"]: {"date": row["date"], "close": row["close"]} for row in rows}


def enrich_holding(row: dict[str, Any]) -> dict[str, Any]:
    if not row:
        return row
    price = latest_prices([row["symbol"]]).get(row["symbol"])
    current_price = price["close"] if price else None
    row["current_price"] = current_price
    row["price_date"] = price["date"] if price else None
    if current_price is None:
        row["current_value"] = None
        row["profit_loss"] = None
        row["profit_loss_pct"] = None
    else:
        current_value = round(float(current_price) * float(row["quantity"]), 2)
        pnl = round(current_value - float(row["invested_amount"]), 2)
        invested = float(row["invested_amount"]) or 1
        row["current_value"] = current_value
        row["profit_loss"] = pnl
        row["profit_loss_pct"] = round(pnl / invested * 100, 2)
    return row


def holdings_summary() -> dict[str, Any]:
    rows = list_holdings()
    invested = round(sum(float(row["invested_amount"] or 0) for row in rows), 2)
    current_rows = [row for row in rows if row.get("current_value") is not None]
    current = round(sum(float(row["current_value"] or 0) for row in current_rows), 2)
    pnl = round(current - invested, 2) if current_rows else None
    pnl_pct = round(pnl / invested * 100, 2) if pnl is not None and invested else None
    return {
        "count": len(rows),
        "invested_amount": invested,
        "current_value": current if current_rows else None,
        "profit_loss": pnl,
        "profit_loss_pct": pnl_pct,
        "as_of": date.today().isoformat(),
    }
