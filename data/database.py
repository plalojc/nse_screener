
# ============================================================
# data/database.py - SQLite layer
# ============================================================
import sqlite3
import pandas as pd
from config import DB_PATH


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")   # enforce FK constraints
    return conn


def init_db():
    conn = get_conn()
    cur  = conn.cursor()

    # == instruments: master symbol reference table ========================
    cur.execute("""
        CREATE TABLE IF NOT EXISTS instruments (
            symbol          TEXT PRIMARY KEY,
            instrument_key  TEXT NOT NULL,
            instrument_name TEXT
        )
    """)

    # == ohlcv: price data only; symbol FK -> instruments ==================
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ohlcv (
            symbol  TEXT REFERENCES instruments(symbol),
            date    TEXT,
            open    REAL,
            high    REAL,
            low     REAL,
            close   REAL,
            volume  INTEGER,
            PRIMARY KEY (symbol, date)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol      TEXT,
            signal_date TEXT,
            signal_type TEXT,       -- BUY / SELL
            price       REAL,
            reason      TEXT,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol              TEXT UNIQUE,
            buy_date            TEXT,
            buy_price           REAL,
            quantity            INTEGER DEFAULT 1,
            target_price        REAL,
            stop_loss_price     REAL,
            trailing_stop_price REAL,
            status              TEXT DEFAULT 'OPEN',   -- OPEN / CLOSED
            exit_price          REAL,
            exit_date           TEXT,
            pnl_pct             REAL
        )
    """)
    # Migrate existing databases that pre-date the trailing_stop_price column
    try:
        cur.execute("ALTER TABLE positions ADD COLUMN trailing_stop_price REAL")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # column already exists

    cur.execute("""
        CREATE TABLE IF NOT EXISTS news_cache (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT,
            url         TEXT UNIQUE,
            published   TEXT,
            source      TEXT,
            fetched_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS breakout_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_date       TEXT    NOT NULL,
            symbol          TEXT    NOT NULL,
            signal_type     TEXT,           -- BREAKOUT / PULLBACK
            close           REAL,
            rsi             REAL,
            vol_ratio       REAL,
            score           INTEGER,
            stage           TEXT,
            ema20           REAL,
            ema50           REAL,
            atr14           REAL,
            swing_low       REAL,
            reasons         TEXT,
            llm_verdict     TEXT,           -- CONFIRM / WEAK / REJECT / SKIPPED
            llm_confidence  INTEGER,        -- 1-10
            llm_reasoning   TEXT,
            llm_model       TEXT,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(scan_date, symbol)       -- one entry per symbol per day
        )
    """)
    # Migrations for existing DBs.
    for col, typedef in [
        ("swing_low",          "REAL"),
        ("llm_verdict",        "TEXT"),
        ("llm_confidence",     "INTEGER"),
        ("llm_reasoning",      "TEXT"),
        ("llm_model",          "TEXT"),
        ("panel_method",       "TEXT"),
        ("vcp_detected",       "INTEGER"),
        ("bull_flag_detected", "INTEGER"),
        ("pattern_score",      "INTEGER"),
    ]:
        try:
            cur.execute(f"ALTER TABLE breakout_log ADD COLUMN {col} {typedef}")
        except sqlite3.OperationalError:
            pass   # column already exists

    # Migrate news_cache: add body column for richer sentiment analysis
    try:
        cur.execute("ALTER TABLE news_cache ADD COLUMN body TEXT")
    except sqlite3.OperationalError:
        pass

    # == invalid_instruments: persistent blacklist of ETFs and no-data symbols
    cur.execute("""
        CREATE TABLE IF NOT EXISTS invalid_instruments (
            symbol   TEXT PRIMARY KEY,
            reason   TEXT NOT NULL,   -- 'ETF' | 'NO_DATA' | 'MANUAL'
            source   TEXT NOT NULL,   -- 'AUTO_ETF' | 'SCAN_EMPTY' | 'MANUAL'
            added_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # One-time migration: scan existing instruments table for ETF-like names
    # and seed them into invalid_instruments (covers data saved before this filter existed).
    _etf_name_kw = ("ETF", "BEES", "INDEX FUND", "FOF")
    existing = cur.execute(
        "SELECT symbol, instrument_name FROM instruments"
    ).fetchall()
    for row in existing:
        sym  = row[0] or ""
        name = (row[1] or "").upper()
        sym_up = sym.upper()
        is_etf = (
            any(kw in name for kw in _etf_name_kw)
            or sym_up.endswith("ETF")
            or sym_up.endswith("BEES")
        )
        if is_etf:
            cur.execute(
                "INSERT OR IGNORE INTO invalid_instruments (symbol, reason, source)"
                " VALUES (?, 'ETF', 'AUTO_ETF')",
                (sym,),
            )

    conn.commit()
    conn.close()
    print("[DB] Tables initialized.")


def save_instruments(df: pd.DataFrame):
    """
    Upsert all NSE EQ instruments into the instruments table.
    *df* must have columns: symbol, instrument_key, name  (from fetch_nse_instruments).
    """
    conn = get_conn()
    cur  = conn.cursor()
    for _, row in df.iterrows():
        cur.execute("""
            INSERT INTO instruments (symbol, instrument_key, instrument_name)
            VALUES (?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                instrument_key  = excluded.instrument_key,
                instrument_name = excluded.instrument_name
        """, (row["symbol"], row["instrument_key"], row.get("name", "")))
    conn.commit()
    conn.close()


def save_ohlcv(symbol: str, df: pd.DataFrame):
    """Upsert OHLCV rows for a symbol (delete-then-insert per symbol)."""
    conn = get_conn()
    conn.execute("DELETE FROM ohlcv WHERE symbol=?", (symbol,))
    df = df.copy()
    df["symbol"] = symbol
    df[["symbol","date","open","high","low","close","volume"]].to_sql(
        "ohlcv", conn, if_exists="append", index=False, method="multi"
    )
    conn.commit()
    conn.close()


def ohlcv_latest_date(symbol: str):
    """Return the latest date string cached for a symbol, or None if absent."""
    conn = get_conn()
    row = conn.execute(
        "SELECT MAX(date) FROM ohlcv WHERE symbol=?", (symbol,)
    ).fetchone()
    conn.close()
    return row[0] if row and row[0] else None


def get_ohlcv_date_map() -> dict:
    """
    Return {symbol: latest_date_str} for ALL symbols in the ohlcv table.
    Single SQL query replaces ~1800 per-symbol ohlcv_latest_date() calls.
    """
    conn = get_conn()
    rows = conn.execute(
        "SELECT symbol, MAX(date) AS max_date FROM ohlcv GROUP BY symbol"
    ).fetchall()
    conn.close()
    return {r["symbol"]: r["max_date"] for r in rows}


def load_ohlcv(symbol: str) -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql(
        "SELECT * FROM ohlcv WHERE symbol=? ORDER BY date",
        conn, params=(symbol,)
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date"])
    return df


def load_ohlcv_upto(symbol: str, upto_date: str) -> pd.DataFrame:
    """Load OHLCV rows for *symbol* with date <= *upto_date* (backtesting: no future leakage)."""
    conn = get_conn()
    df = pd.read_sql(
        "SELECT * FROM ohlcv WHERE symbol=? AND date<=? ORDER BY date",
        conn, params=(symbol, upto_date)
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date"])
    return df


def load_ohlcv_range(symbol: str, from_date: str, to_date: str) -> pd.DataFrame:
    """Load OHLCV rows strictly AFTER *from_date* up to and including *to_date*.
    Used to fetch the forward-looking candles for backtest outcome evaluation.
    """
    conn = get_conn()
    df = pd.read_sql(
        "SELECT * FROM ohlcv WHERE symbol=? AND date>? AND date<=? ORDER BY date",
        conn, params=(symbol, from_date, to_date)
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date"])
    return df


def get_symbols_with_data_upto(upto_date: str) -> list:
    """Return all symbols that have at least one OHLCV row on or before *upto_date*."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT symbol FROM ohlcv WHERE date <= ?", (upto_date,)
    ).fetchall()
    conn.close()
    return [r["symbol"] for r in rows]


def save_signal(symbol, signal_type, price, reason):
    conn = get_conn()
    from datetime import date
    conn.execute(
        "INSERT INTO signals (symbol, signal_date, signal_type, price, reason) VALUES (?,?,?,?,?)",
        (symbol, str(date.today()), signal_type, price, reason)
    )
    conn.commit()
    conn.close()


def open_position(symbol, buy_price, target_price, stop_loss_price,
                  trailing_stop_price=None):
    """Open a new position. trailing_stop_price defaults to stop_loss_price."""
    conn = get_conn()
    from datetime import date
    trail = trailing_stop_price if trailing_stop_price is not None else stop_loss_price
    try:
        conn.execute("""
            INSERT INTO positions
                (symbol, buy_date, buy_price, target_price,
                 stop_loss_price, trailing_stop_price)
            VALUES (?,?,?,?,?,?)
        """, (symbol, str(date.today()), buy_price, target_price,
              stop_loss_price, trail))
        conn.commit()
    except sqlite3.IntegrityError:
        pass   # already have open position in this stock
    conn.close()

def reset_positions():
    conn = get_conn()
    conn.execute("DELETE FROM positions")
    conn.commit()
    conn.close()
    print("Cleared all old positions!")


def update_trailing_stop(symbol: str, new_trail: float):
    """
    Ratchet the trailing stop UP only == never move it down.
    Uses a single SQL conditional update to avoid a race condition.
    """
    conn = get_conn()
    conn.execute("""
        UPDATE positions
        SET trailing_stop_price = ?
        WHERE symbol = ?
          AND status = 'OPEN'
          AND (trailing_stop_price IS NULL OR trailing_stop_price < ?)
    """, (new_trail, symbol, new_trail))
    conn.commit()
    conn.close()


def get_open_positions() -> list:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM positions WHERE status='OPEN'").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def close_position(symbol, exit_price, pnl_pct):
    conn = get_conn()
    from datetime import date
    conn.execute("""
        UPDATE positions
        SET status='CLOSED', exit_price=?, exit_date=?, pnl_pct=?
        WHERE symbol=? AND status='OPEN'
    """, (exit_price, str(date.today()), pnl_pct, symbol))
    conn.commit()
    conn.close()


# == Breakout Log ===========================================================

def get_llm_verdict_cache(
    scan_date: str,
    panel_method: str | None = None,
    llm_model: str | None = None,
) -> dict:
    """
    Return already-validated LLM verdicts for a given scan_date.
    Only returns rows where llm_verdict is a real verdict (not SKIPPED).
    Result: {symbol: {llm_verdict, llm_confidence, llm_reasoning}}
    Used to skip LLM API calls for signals already validated today.

    When panel_method/llm_model are provided, only cache entries produced by
    that validator/model are reused. This prevents Grok runs from reusing Gemini
    verdicts, and also forces old rows with missing model metadata to be
    revalidated once.
    """
    conn = get_conn()
    sql = """
        SELECT symbol, llm_verdict, llm_confidence, llm_reasoning,
               panel_method, llm_model
        FROM   breakout_log
        WHERE  scan_date = ?
          AND  llm_verdict NOT IN ('SKIPPED', '')
          AND  llm_verdict IS NOT NULL
    """
    params = [scan_date]
    if panel_method:
        sql += " AND panel_method = ?"
        params.append(panel_method)
    if llm_model:
        sql += " AND llm_model = ?"
        params.append(llm_model)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return {
        r["symbol"]: {
            "llm_verdict":    r["llm_verdict"],
            "llm_confidence": r["llm_confidence"],
            "llm_reasoning":  r["llm_reasoning"],
            "panel_method":   r["panel_method"],
            "llm_model":      r["llm_model"],
        }
        for r in rows
    }


def save_breakout_log(scan_date: str, sig: dict):
    """Insert or update a Gemini-validated breakout signal row."""
    conn = get_conn()
    conn.execute("""
        INSERT INTO breakout_log
            (scan_date, symbol, signal_type, close, rsi, vol_ratio, score,
             stage, ema20, ema50, atr14, swing_low, reasons,
             llm_verdict, llm_confidence, llm_reasoning,
             panel_method, llm_model, vcp_detected, bull_flag_detected, pattern_score)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(scan_date, symbol) DO UPDATE SET
            signal_type = excluded.signal_type,
            close       = excluded.close,
            rsi         = excluded.rsi,
            vol_ratio   = excluded.vol_ratio,
            score       = excluded.score,
            stage       = excluded.stage,
            ema20       = excluded.ema20,
            ema50       = excluded.ema50,
            atr14       = excluded.atr14,
            swing_low   = excluded.swing_low,
            reasons     = excluded.reasons,
            llm_verdict = CASE
                WHEN excluded.llm_verdict NOT IN ('SKIPPED', '') THEN excluded.llm_verdict
                WHEN llm_verdict IS NULL OR llm_verdict IN ('SKIPPED', '') THEN excluded.llm_verdict
                ELSE llm_verdict
            END,
            llm_confidence = CASE
                WHEN excluded.llm_verdict NOT IN ('SKIPPED', '') THEN excluded.llm_confidence
                WHEN llm_verdict IS NULL OR llm_verdict IN ('SKIPPED', '') THEN excluded.llm_confidence
                ELSE llm_confidence
            END,
            llm_reasoning = CASE
                WHEN excluded.llm_verdict NOT IN ('SKIPPED', '') THEN excluded.llm_reasoning
                WHEN llm_verdict IS NULL OR llm_verdict IN ('SKIPPED', '') THEN excluded.llm_reasoning
                ELSE llm_reasoning
            END,
            panel_method = CASE
                WHEN excluded.llm_verdict NOT IN ('SKIPPED', '') THEN excluded.panel_method
                WHEN llm_verdict IS NULL OR llm_verdict IN ('SKIPPED', '') THEN excluded.panel_method
                ELSE panel_method
            END,
            llm_model = CASE
                WHEN excluded.llm_verdict NOT IN ('SKIPPED', '') THEN excluded.llm_model
                WHEN llm_verdict IS NULL OR llm_verdict IN ('SKIPPED', '') THEN excluded.llm_model
                ELSE llm_model
            END,
            vcp_detected       = COALESCE(excluded.vcp_detected, vcp_detected),
            bull_flag_detected = COALESCE(excluded.bull_flag_detected, bull_flag_detected),
            pattern_score      = COALESCE(excluded.pattern_score, pattern_score)
    """, (
        scan_date,
        sig.get("symbol"),
        sig.get("signal_type"),
        sig.get("close"),
        sig.get("rsi"),
        sig.get("vol_ratio"),
        sig.get("score"),
        sig.get("stage"),
        sig.get("ema20"),
        sig.get("ema50"),
        sig.get("atr14"),
        sig.get("swing_low"),
        sig.get("reasons"),
        sig.get("llm_verdict", "SKIPPED"),
        sig.get("llm_confidence"),
        sig.get("llm_reasoning"),
        sig.get("panel_method", "GEMINI_DIRECT"),
        sig.get("llm_model"),
        sig.get("vcp_detected"),
        sig.get("bull_flag_detected"),
        sig.get("pattern_score"),
    ))
    conn.commit()
    conn.close()

# == Invalid Instruments Blacklist =========================================

def add_invalid_instrument(symbol: str, reason: str, source: str) -> None:
    """Add a single symbol to the blacklist (INSERT OR IGNORE - safe to call repeatedly)."""
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO invalid_instruments (symbol, reason, source) VALUES (?, ?, ?)",
        (symbol, reason, source),
    )
    conn.commit()
    conn.close()


def bulk_add_invalid_instruments(rows: list) -> int:
    """Bulk-insert symbols into the blacklist.
    Each element must be a dict with keys: symbol, reason, source.
    Uses INSERT OR IGNORE - safe to re-run every scan (duplicates are skipped).
    Returns the number of newly inserted rows."""
    if not rows:
        return 0
    conn = get_conn()
    cur = conn.executemany(
        "INSERT OR IGNORE INTO invalid_instruments (symbol, reason, source)"
        " VALUES (:symbol, :reason, :source)",
        rows,
    )
    added = cur.rowcount
    conn.commit()
    conn.close()
    return added


def get_invalid_symbols() -> set:
    """Return the full set of blacklisted symbols for O(1) scan-loop filtering."""
    conn = get_conn()
    rows = conn.execute("SELECT symbol FROM invalid_instruments").fetchall()
    conn.close()
    return {r["symbol"] for r in rows}


def get_breakout_log(days: int = 30) -> pd.DataFrame:
    """Return the last `days` worth of breakout_log rows as a DataFrame."""
    conn = get_conn()
    df = pd.read_sql(
        """
        SELECT scan_date, symbol, signal_type, close, rsi, vol_ratio, score,
               stage, ema20, ema50, atr14, reasons,
               llm_verdict, llm_confidence, llm_reasoning, created_at
        FROM   breakout_log
        WHERE  scan_date >= date('now', ?)
        ORDER  BY scan_date DESC, score DESC
        """,
        conn,
        params=(f"-{days} days",),
    )
    conn.close()
    return df


def delete_breakout_log(scan_date: str) -> int:
    """Delete all breakout_log rows for a specific scan_date. Returns rows deleted."""
    conn = get_conn()
    cur = conn.execute(
        "DELETE FROM breakout_log WHERE scan_date = ?", (scan_date,)
    )
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return deleted

