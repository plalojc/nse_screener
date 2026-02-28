
# ============================================================
# data/database.py – SQLite layer
# ============================================================
import sqlite3
import pandas as pd
from config import DB_PATH


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur  = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ohlcv (
            symbol      TEXT,
            date        TEXT,
            open        REAL,
            high        REAL,
            low         REAL,
            close       REAL,
            volume      INTEGER,
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
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(scan_date, symbol)       -- one entry per symbol per day
        )
    """)
    # Migrations for existing DBs
    for col, typedef in [
        ("swing_low",      "REAL"),
        ("llm_verdict",    "TEXT"),
        ("llm_confidence", "INTEGER"),
        ("llm_reasoning",  "TEXT"),
    ]:
        try:
            cur.execute(f"ALTER TABLE breakout_log ADD COLUMN {col} {typedef}")
        except sqlite3.OperationalError:
            pass

    conn.commit()
    conn.close()
    print("[DB] Tables initialized.")


def save_ohlcv(symbol: str, df: pd.DataFrame):
    """Upsert OHLCV rows for a symbol (delete-then-insert per symbol)."""
    conn = get_conn()
    # Delete existing rows for this symbol only – keeps all other symbols intact
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
    Ratchet the trailing stop UP only — never move it down.
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


# ── Breakout Log ──────────────────────────────────────────────────────────────

def get_llm_verdict_cache(scan_date: str) -> dict:
    """
    Return already-validated LLM verdicts for a given scan_date.
    Only returns rows where llm_verdict is a real verdict (not SKIPPED).
    Result: {symbol: {llm_verdict, llm_confidence, llm_reasoning}}
    Used to skip LLM API calls for signals already validated today.
    """
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT symbol, llm_verdict, llm_confidence, llm_reasoning
        FROM   breakout_log
        WHERE  scan_date = ?
          AND  llm_verdict NOT IN ('SKIPPED', '')
          AND  llm_verdict IS NOT NULL
        """,
        (scan_date,)
    ).fetchall()
    conn.close()
    return {
        r["symbol"]: {
            "llm_verdict":    r["llm_verdict"],
            "llm_confidence": r["llm_confidence"],
            "llm_reasoning":  r["llm_reasoning"],
        }
        for r in rows
    }


def save_breakout_log(scan_date: str, sig: dict):
    """
    Insert or replace a breakout signal row in breakout_log.
    IMPORTANT: Never overwrites an existing real LLM verdict with SKIPPED —
    preserves validated verdicts across re-runs on the same day.
    """
    conn = get_conn()
    conn.execute("""
        INSERT INTO breakout_log
            (scan_date, symbol, signal_type, close, rsi, vol_ratio, score,
             stage, ema20, ema50, atr14, swing_low, reasons,
             llm_verdict, llm_confidence, llm_reasoning)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(scan_date, symbol) DO UPDATE SET
            signal_type    = excluded.signal_type,
            close          = excluded.close,
            rsi            = excluded.rsi,
            vol_ratio      = excluded.vol_ratio,
            score          = excluded.score,
            stage          = excluded.stage,
            ema20          = excluded.ema20,
            ema50          = excluded.ema50,
            atr14          = excluded.atr14,
            swing_low      = excluded.swing_low,
            reasons        = excluded.reasons,
            -- Only update LLM fields if the new value is a real verdict
            -- or if there is no existing real verdict stored yet
            llm_verdict    = CASE
                WHEN excluded.llm_verdict NOT IN ('SKIPPED', '') THEN excluded.llm_verdict
                WHEN llm_verdict IS NULL OR llm_verdict IN ('SKIPPED', '') THEN excluded.llm_verdict
                ELSE llm_verdict
            END,
            llm_confidence = CASE
                WHEN excluded.llm_verdict NOT IN ('SKIPPED', '') THEN excluded.llm_confidence
                WHEN llm_verdict IS NULL OR llm_verdict IN ('SKIPPED', '') THEN excluded.llm_confidence
                ELSE llm_confidence
            END,
            llm_reasoning  = CASE
                WHEN excluded.llm_verdict NOT IN ('SKIPPED', '') THEN excluded.llm_reasoning
                WHEN llm_verdict IS NULL OR llm_verdict IN ('SKIPPED', '') THEN excluded.llm_reasoning
                ELSE llm_reasoning
            END
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
    ))
    conn.commit()
    conn.close()


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
