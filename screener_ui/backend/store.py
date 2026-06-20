from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from data.db_backend import (
    connect,
    ensure_schemas,
    execute,
    is_postgres,
    read_dataframe,
    system_schema,
    table_name,
    user_schema,
)

from .auth import default_user_email
from .settings import BHAVCOPY_DB_PATH, UI_DB_PATH


T_WATCHLIST = table_name("watchlist", user_schema())
T_HOLDINGS = table_name("holdings", user_schema())
T_HOLDING_SALES = table_name("holding_sales", user_schema())
T_UI_SETTINGS = table_name("ui_settings", user_schema())
T_BHAVCOPY_OHLCV = table_name("bhavcopy_ohlcv", system_schema())


def _connect(path: Path = UI_DB_PATH):
    return connect(path)


def _id_type() -> str:
    return "BIGSERIAL" if is_postgres() else "INTEGER"


def _now_default() -> str:
    return "TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP" if is_postgres() else "TEXT DEFAULT (datetime('now'))"


def init_store() -> None:
    with _connect() as conn:
        ensure_schemas(conn)
        id_type = _id_type()
        now_default = _now_default()
        default_owner = default_user_email()
        execute(conn, f"""
            CREATE TABLE IF NOT EXISTS {T_WATCHLIST} (
                id INTEGER PRIMARY KEY,
                user_email TEXT NOT NULL DEFAULT '',
                symbol TEXT NOT NULL,
                notes TEXT,
                target_price REAL,
                added_price REAL,
                added_price_date TEXT,
                created_at {now_default},
                updated_at {now_default},
                UNIQUE(user_email, symbol)
            )
        """.replace("id INTEGER PRIMARY KEY", f"id {id_type} PRIMARY KEY"))
        _migrate_watchlist_user_scope(conn, default_owner)
        _add_column(conn, T_WATCHLIST, "user_email", "TEXT")
        _add_column(conn, T_WATCHLIST, "added_price", "REAL")
        _add_column(conn, T_WATCHLIST, "added_price_date", "TEXT")
        execute(conn, f"UPDATE {T_WATCHLIST} SET user_email=? WHERE user_email IS NULL OR user_email=''", (default_owner,))
        execute(conn, f"""
            CREATE TABLE IF NOT EXISTS {T_HOLDINGS} (
                id INTEGER PRIMARY KEY,
                user_email TEXT NOT NULL DEFAULT '',
                symbol TEXT NOT NULL,
                buy_date TEXT NOT NULL,
                quantity REAL NOT NULL,
                buy_price REAL NOT NULL,
                invested_amount REAL NOT NULL,
                notes TEXT,
                created_at {now_default},
                updated_at {now_default}
            )
        """.replace("id INTEGER PRIMARY KEY", f"id {id_type} PRIMARY KEY"))
        _add_column(conn, T_HOLDINGS, "user_email", "TEXT")
        execute(conn, f"UPDATE {T_HOLDINGS} SET user_email=? WHERE user_email IS NULL OR user_email=''", (default_owner,))
        execute(conn, f"""
            CREATE TABLE IF NOT EXISTS {T_HOLDING_SALES} (
                id INTEGER PRIMARY KEY,
                user_email TEXT NOT NULL DEFAULT '',
                holding_id INTEGER,
                symbol TEXT NOT NULL,
                sell_date TEXT NOT NULL,
                quantity REAL NOT NULL,
                buy_date TEXT,
                buy_price REAL,
                buy_amount REAL,
                sell_price REAL NOT NULL,
                sell_amount REAL NOT NULL,
                realized_profit_loss REAL,
                notes TEXT,
                created_at {now_default}
            )
        """.replace("id INTEGER PRIMARY KEY", f"id {id_type} PRIMARY KEY"))
        _add_column(conn, T_HOLDING_SALES, "user_email", "TEXT")
        _add_column(conn, T_HOLDING_SALES, "buy_date", "TEXT")
        _add_column(conn, T_HOLDING_SALES, "buy_price", "REAL")
        _add_column(conn, T_HOLDING_SALES, "buy_amount", "REAL")
        execute(conn, f"UPDATE {T_HOLDING_SALES} SET user_email=? WHERE user_email IS NULL OR user_email=''", (default_owner,))
        execute(conn, f"""
            CREATE TABLE IF NOT EXISTS {T_UI_SETTINGS} (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at {now_default}
            )
        """)
        conn.commit()


def _migrate_watchlist_user_scope(conn, default_owner: str) -> None:
    if is_postgres():
        try:
            execute(conn, f"CREATE UNIQUE INDEX IF NOT EXISTS watchlist_user_symbol_idx ON {T_WATCHLIST} (user_email, symbol)")
        except Exception:
            pass
        return
    try:
        table_sql = execute(
            conn,
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='watchlist'",
        ).fetchone()
    except Exception:
        return
    create_sql = str(table_sql["sql"] if table_sql else "")
    if "symbol TEXT NOT NULL UNIQUE" not in create_sql:
        return
    execute(conn, "ALTER TABLE watchlist RENAME TO watchlist_legacy_unique")
    execute(conn, """
        CREATE TABLE watchlist (
            id INTEGER PRIMARY KEY,
            user_email TEXT NOT NULL DEFAULT '',
            symbol TEXT NOT NULL,
            notes TEXT,
            target_price REAL,
            added_price REAL,
            added_price_date TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(user_email, symbol)
        )
    """)
    execute(conn, """
        INSERT INTO watchlist
            (id, user_email, symbol, notes, target_price, added_price, added_price_date, created_at, updated_at)
        SELECT id, ?, symbol, notes, target_price, added_price, added_price_date, created_at, updated_at
        FROM watchlist_legacy_unique
    """, (default_owner,))
    execute(conn, "DROP TABLE watchlist_legacy_unique")


def _row_to_dict(row: Any | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def _add_column(conn, table: str, col: str, typedef: str) -> None:
    try:
        execute(conn, f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {typedef}")
    except Exception:
        try:
            execute(conn, f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")
        except Exception:
            pass


def add_watchlist(user_email: str, symbol: str, notes: str = "", target_price: float | None = None) -> dict:
    symbol = symbol.strip().upper()
    price = latest_prices([symbol]).get(symbol)
    added_price = price["close"] if price else None
    added_price_date = price["date"] if price else None
    with _connect() as conn:
        existing = execute(conn, f"SELECT * FROM {T_WATCHLIST} WHERE user_email=? AND symbol=?", (user_email, symbol)).fetchone()
        if existing:
            row = existing
        else:
            execute(conn, f"""
                INSERT INTO {T_WATCHLIST}
                    (user_email, symbol, notes, target_price, added_price, added_price_date, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """, (user_email, symbol, notes.strip(), target_price, added_price, added_price_date))
            row = execute(conn, f"SELECT * FROM {T_WATCHLIST} WHERE user_email=? AND symbol=?", (user_email, symbol)).fetchone()
        conn.commit()
    result = _row_to_dict(row) or {}
    result["created"] = not bool(existing)
    return enrich_watchlist(result)


def list_watchlist(user_email: str) -> list[dict]:
    backfill_watchlist_added_prices(user_email)
    with _connect() as conn:
        rows = execute(conn, f"""
            SELECT * FROM {T_WATCHLIST}
            WHERE user_email=?
            ORDER BY created_at DESC, symbol
        """, (user_email,)).fetchall()
    return enrich_watchlist_rows([dict(row) for row in rows])


def update_watchlist(user_email: str, item_id: int, payload: dict[str, Any]) -> dict | None:
    target_price = payload.get("target_price")
    notes = str(payload.get("notes") or "").strip()
    with _connect() as conn:
        if is_postgres():
            row = execute(conn, f"""
                UPDATE {T_WATCHLIST}
                SET notes=?, target_price=?
                WHERE id=? AND user_email=?
                RETURNING *
            """, (notes, target_price, item_id, user_email)).fetchone()
        else:
            execute(conn, f"""
                UPDATE {T_WATCHLIST}
                SET notes=?, target_price=?
                WHERE id=? AND user_email=?
            """, (notes, target_price, item_id, user_email))
            row = execute(conn, f"SELECT * FROM {T_WATCHLIST} WHERE id=? AND user_email=?", (item_id, user_email)).fetchone()
        conn.commit()
    return enrich_watchlist(_row_to_dict(row) or {}) if row else None


def delete_watchlist(user_email: str, item_id: int) -> None:
    with _connect() as conn:
        execute(conn, f"DELETE FROM {T_WATCHLIST} WHERE id=? AND user_email=?", (item_id, user_email))
        conn.commit()


def clear_watchlist(user_email: str) -> int:
    with _connect() as conn:
        cur = execute(conn, f"DELETE FROM {T_WATCHLIST} WHERE user_email=?", (user_email,))
        deleted = getattr(cur, "rowcount", 0)
        conn.commit()
    return deleted


def backfill_watchlist_added_prices(user_email: str) -> None:
    with _connect() as conn:
        try:
            rows = execute(conn, f"""
                SELECT id, symbol
                FROM {T_WATCHLIST}
                WHERE user_email=? AND added_price IS NULL
            """, (user_email,)).fetchall()
        except Exception:
            return
        missing = [dict(row) for row in rows]
        if not missing:
            return
        prices = latest_prices([row["symbol"] for row in missing])
        for row in missing:
            price = prices.get(row["symbol"])
            if not price:
                continue
            execute(conn, f"""
                UPDATE {T_WATCHLIST}
                SET added_price=?, added_price_date=?
                WHERE id=?
            """, (price["close"], price["date"], row["id"]))
        conn.commit()


def add_holding(user_email: str, symbol: str, buy_date: str, quantity: float, buy_price: float, notes: str = "") -> dict:
    symbol = symbol.strip().upper()
    invested = round(float(quantity) * float(buy_price), 2)
    with _connect() as conn:
        if is_postgres():
            row = execute(conn, f"""
                INSERT INTO {T_HOLDINGS}
                    (user_email, symbol, buy_date, quantity, buy_price, invested_amount, notes, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                RETURNING *
            """, (user_email, symbol, buy_date, quantity, buy_price, invested, notes.strip())).fetchone()
        else:
            cur = execute(conn, f"""
                INSERT INTO {T_HOLDINGS}
                    (user_email, symbol, buy_date, quantity, buy_price, invested_amount, notes, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """, (user_email, symbol, buy_date, quantity, buy_price, invested, notes.strip()))
            row = execute(conn, f"SELECT * FROM {T_HOLDINGS} WHERE id=?", (cur.lastrowid,)).fetchone()
        conn.commit()
    return enrich_holding(_row_to_dict(row) or {})


def update_holding(user_email: str, item_id: int, payload: dict[str, Any]) -> dict | None:
    existing = get_holding(user_email, item_id)
    if not existing:
        return None
    symbol = str(payload.get("symbol", existing["symbol"])).strip().upper()
    buy_date = str(payload.get("buy_date", existing["buy_date"]))
    quantity = float(payload.get("quantity", existing["quantity"]))
    buy_price = float(payload.get("buy_price", existing["buy_price"]))
    notes = str(payload.get("notes", existing.get("notes") or "")).strip()
    invested = round(quantity * buy_price, 2)

    with _connect() as conn:
        if is_postgres():
            row = execute(conn, f"""
                UPDATE {T_HOLDINGS}
                SET symbol=?, buy_date=?, quantity=?, buy_price=?,
                    invested_amount=?, notes=?, updated_at=datetime('now')
                WHERE id=? AND user_email=?
                RETURNING *
            """, (symbol, buy_date, quantity, buy_price, invested, notes, item_id, user_email)).fetchone()
        else:
            execute(conn, f"""
                UPDATE {T_HOLDINGS}
                SET symbol=?, buy_date=?, quantity=?, buy_price=?,
                    invested_amount=?, notes=?, updated_at=datetime('now')
                WHERE id=? AND user_email=?
            """, (symbol, buy_date, quantity, buy_price, invested, notes, item_id, user_email))
            row = execute(conn, f"SELECT * FROM {T_HOLDINGS} WHERE id=? AND user_email=?", (item_id, user_email)).fetchone()
        conn.commit()
    return enrich_holding(_row_to_dict(row) or {})


def get_holding(user_email: str, item_id: int) -> dict | None:
    with _connect() as conn:
        row = execute(conn, f"SELECT * FROM {T_HOLDINGS} WHERE id=? AND user_email=?", (item_id, user_email)).fetchone()
    return _row_to_dict(row)


def list_holdings(user_email: str) -> list[dict]:
    with _connect() as conn:
        rows = execute(conn, f"""
            SELECT * FROM {T_HOLDINGS}
            WHERE user_email=?
            ORDER BY buy_date DESC, id DESC
        """, (user_email,)).fetchall()
    return [enrich_holding(dict(row)) for row in rows]


def delete_holding(user_email: str, item_id: int) -> None:
    with _connect() as conn:
        execute(conn, f"DELETE FROM {T_HOLDINGS} WHERE id=? AND user_email=?", (item_id, user_email))
        conn.commit()


def sell_holding(
    user_email: str,
    item_id: int,
    sell_date: str,
    quantity: float,
    sell_price: float,
    notes: str = "",
) -> dict[str, Any] | None:
    holding = get_holding(user_email, item_id)
    if not holding:
        return None

    sell_qty = float(quantity)
    held_qty = float(holding["quantity"])
    if sell_qty <= 0 or sell_qty > held_qty:
        raise ValueError("Sell quantity must be greater than 0 and not more than current quantity")

    buy_price = float(holding["buy_price"])
    buy_amount = round(sell_qty * buy_price, 2)
    sell_amount = round(sell_qty * float(sell_price), 2)
    realized = round(sell_amount - buy_amount, 2)
    remaining_qty = round(held_qty - sell_qty, 6)

    with _connect() as conn:
        execute(conn, f"""
            INSERT INTO {T_HOLDING_SALES}
                (user_email, holding_id, symbol, sell_date, quantity, buy_date, buy_price,
                 buy_amount, sell_price, sell_amount, realized_profit_loss, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_email,
            item_id,
            holding["symbol"],
            sell_date,
            sell_qty,
            holding["buy_date"],
            buy_price,
            buy_amount,
            sell_price,
            sell_amount,
            realized,
            notes.strip(),
        ))
        if remaining_qty <= 0:
            execute(conn, f"DELETE FROM {T_HOLDINGS} WHERE id=? AND user_email=?", (item_id, user_email))
            next_holding = None
        else:
            remaining_invested = round(remaining_qty * buy_price, 2)
            execute(conn, f"""
                UPDATE {T_HOLDINGS}
                SET quantity=?, invested_amount=?, updated_at=datetime('now')
                WHERE id=? AND user_email=?
            """, (remaining_qty, remaining_invested, item_id, user_email))
            next_holding = execute(conn, f"SELECT * FROM {T_HOLDINGS} WHERE id=? AND user_email=?", (item_id, user_email)).fetchone()
        conn.commit()

    return {
        "status": "sold",
        "symbol": holding["symbol"],
        "sold_quantity": sell_qty,
        "buy_amount": buy_amount,
        "sell_amount": sell_amount,
        "realized_profit_loss": realized,
        "holding": enrich_holding(_row_to_dict(next_holding) or {}) if next_holding else None,
    }


def profit_loss_report(user_email: str, from_date: str, to_date: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []

    with _connect() as conn:
        sell_rows = execute(conn, f"""
            SELECT
                s.id,
                s.holding_id,
                s.symbol,
                s.sell_date,
                s.quantity,
                COALESCE(NULLIF(s.buy_date, ''), h.buy_date) AS buy_date,
                COALESCE(s.buy_price, h.buy_price) AS buy_price,
                COALESCE(s.buy_amount, s.quantity * h.buy_price) AS buy_amount,
                s.sell_price,
                s.sell_amount,
                s.realized_profit_loss
            FROM {T_HOLDING_SALES} s
            LEFT JOIN {T_HOLDINGS} h ON h.id = s.holding_id AND h.user_email = s.user_email
            WHERE s.user_email=? AND s.sell_date >= ? AND s.sell_date <= ?
            ORDER BY s.sell_date, s.symbol, s.id
        """, (user_email, from_date, to_date)).fetchall()

    for row in sell_rows:
        item = dict(row)
        buy_amount = item.get("buy_amount")
        if buy_amount is None and item.get("sell_amount") is not None and item.get("realized_profit_loss") is not None:
            buy_amount = round(float(item["sell_amount"]) - float(item["realized_profit_loss"]), 2)
        buy_price = item.get("buy_price")
        if buy_price is None and buy_amount is not None and float(item["quantity"] or 0):
            buy_price = round(float(buy_amount) / float(item["quantity"]), 2)
        rows.append({
            "id": item["id"],
            "date": item["sell_date"],
            "symbol": item["symbol"],
            "quantity": item["quantity"],
            "buy_date": item.get("buy_date"),
            "buy_price": buy_price,
            "buy_amount": buy_amount,
            "sell_date": item["sell_date"],
            "sell_price": item["sell_price"],
            "sell_amount": item["sell_amount"],
            "profit_loss": item["realized_profit_loss"],
        })

    rows.sort(key=lambda item: (item["date"] or "", item["symbol"]))
    total_buy = round(sum(float(row["buy_amount"] or 0) for row in rows), 2)
    total_sell = round(sum(float(row["sell_amount"] or 0) for row in rows), 2)
    realized_pnl = round(sum(float(row["profit_loss"] or 0) for row in rows), 2)

    return {
        "from_date": from_date,
        "to_date": to_date,
        "rows": rows,
        "summary": {
            "total_buy_amount": total_buy,
            "total_sell_amount": total_sell,
            "profit_loss": realized_pnl,
            "sell_count": len(rows),
        },
    }


def delete_profit_loss_sale(user_email: str, sale_id: int) -> bool:
    with _connect() as conn:
        cursor = execute(conn, f"DELETE FROM {T_HOLDING_SALES} WHERE id=? AND user_email=?", (sale_id, user_email))
        conn.commit()
        return cursor.rowcount > 0


def delete_user_data(user_email: str) -> None:
    init_store()
    settings_prefix = f"{user_email}:%"
    with _connect() as conn:
        execute(conn, f"DELETE FROM {T_HOLDING_SALES} WHERE user_email=?", (user_email,))
        execute(conn, f"DELETE FROM {T_HOLDINGS} WHERE user_email=?", (user_email,))
        execute(conn, f"DELETE FROM {T_WATCHLIST} WHERE user_email=?", (user_email,))
        execute(conn, f"DELETE FROM {T_UI_SETTINGS} WHERE key LIKE ?", (settings_prefix,))
        conn.commit()


def _setting_key(key: str, user_email: str | None = None) -> str:
    return f"{user_email}:{key}" if user_email else key


def set_setting(key: str, value: str, user_email: str | None = None) -> None:
    storage_key = _setting_key(key, user_email)
    with _connect() as conn:
        execute(conn, f"""
            INSERT INTO {T_UI_SETTINGS} (key, value, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET
                value=excluded.value,
                updated_at=datetime('now')
        """, (storage_key, value))
        conn.commit()


def get_setting(key: str, default: str = "", user_email: str | None = None) -> str:
    storage_key = _setting_key(key, user_email)
    with _connect() as conn:
        row = execute(conn, f"SELECT value FROM {T_UI_SETTINGS} WHERE key=?", (storage_key,)).fetchone()
    return str(row["value"]) if row else default


def get_settings(keys: dict[str, str], user_email: str | None = None) -> dict[str, str]:
    values = {}
    with _connect() as conn:
        for key, default in keys.items():
            row = execute(conn, f"SELECT value FROM {T_UI_SETTINGS} WHERE key=?", (_setting_key(key, user_email),)).fetchone()
            values[key] = str(row["value"]) if row else default
    return values


def latest_prices(symbols: list[str] | None = None) -> dict[str, dict[str, Any]]:
    if not is_postgres() and not BHAVCOPY_DB_PATH.exists():
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
            FROM {T_BHAVCOPY_OHLCV}
            {where}
            GROUP BY symbol
        )
        SELECT b.symbol, b.date, b.close
        FROM {T_BHAVCOPY_OHLCV} b
        JOIN latest l ON l.symbol=b.symbol AND l.max_date=b.date
    """
    try:
        with _connect(BHAVCOPY_DB_PATH) as conn:
            df = read_dataframe(conn, sql, params)
    except Exception:
        return {}
    if df.empty:
        return {}
    return {
        row["symbol"]: {"date": row["date"], "close": row["close"]}
        for row in df.to_dict("records")
    }


def enrich_watchlist(row: dict[str, Any]) -> dict[str, Any]:
    if not row:
        return row
    return enrich_watchlist_rows([row])[0]


def enrich_watchlist_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return rows
    symbols = [str(row.get("symbol") or "").upper() for row in rows if row.get("symbol")]
    prices = latest_prices(symbols)
    for row in rows:
        symbol = str(row.get("symbol") or "").upper()
        price = prices.get(symbol)
        current_price = price["close"] if price else None
        added_price = row.get("added_price")
        row["current_price"] = current_price
        row["price_date"] = price["date"] if price else None
        if current_price is None or added_price in (None, ""):
            row["profit_loss"] = None
            row["profit_loss_pct"] = None
            continue
        added = float(added_price)
        pnl = round(float(current_price) - added, 2)
        row["profit_loss"] = pnl
        row["profit_loss_pct"] = round(pnl / added * 100, 2) if added else None
    return rows


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


def holdings_summary(user_email: str) -> dict[str, Any]:
    rows = list_holdings(user_email)
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
