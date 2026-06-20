from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from config import DB_PATH
from data.db_backend import (
    connect,
    ensure_schemas,
    execute,
    executemany,
    integrity_error_types,
    is_postgres,
    read_dataframe,
    system_schema,
    table_name,
    user_schema,
)


T_SIGNALS = table_name("signals", user_schema())
T_POSITIONS = table_name("positions", user_schema())
T_BREAKOUT_LOG = table_name("breakout_log", system_schema())
T_LLM_EVALUATIONS = table_name("llm_evaluations", system_schema())
T_CATALYST_EVENTS = table_name("catalyst_events", system_schema())
T_INVALID_INSTRUMENTS = table_name("invalid_instruments", system_schema())
DB_WRITE_BATCH_SIZE = 100


def get_conn():
    return connect(DB_PATH)


def _id_type() -> str:
    return "BIGSERIAL" if is_postgres() else "INTEGER"


def _now_default() -> str:
    return "TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP" if is_postgres() else "DATETIME DEFAULT CURRENT_TIMESTAMP"


def _add_column(conn, table: str, col: str, typedef: str) -> None:
    if is_postgres():
        execute(conn, f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {typedef}")
        return
    try:
        execute(conn, f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")
    except Exception:
        pass


def init_db():
    conn = get_conn()
    ensure_schemas(conn)
    id_type = _id_type()
    now_default = _now_default()

    execute(conn, f"""
        CREATE TABLE IF NOT EXISTS {T_SIGNALS} (
            id          {id_type} PRIMARY KEY,
            symbol      TEXT,
            signal_date TEXT,
            signal_type TEXT,
            price       REAL,
            reason      TEXT,
            created_at  {now_default}
        )
    """)

    execute(conn, f"""
        CREATE TABLE IF NOT EXISTS {T_POSITIONS} (
            id                  {id_type} PRIMARY KEY,
            symbol              TEXT UNIQUE,
            buy_date            TEXT,
            buy_price           REAL,
            quantity            INTEGER DEFAULT 1,
            target_price        REAL,
            stop_loss_price     REAL,
            trailing_stop_price REAL,
            status              TEXT DEFAULT 'OPEN',
            exit_price          REAL,
            exit_date           TEXT,
            pnl_pct             REAL
        )
    """)
    _add_column(conn, T_POSITIONS, "trailing_stop_price", "REAL")

    execute(conn, f"""
        CREATE TABLE IF NOT EXISTS {T_BREAKOUT_LOG} (
            id                  {id_type} PRIMARY KEY,
            scan_date           TEXT NOT NULL,
            symbol              TEXT NOT NULL,
            signal_type         TEXT,
            close               REAL,
            rsi                 REAL,
            vol_ratio           REAL,
            score               INTEGER,
            stage               TEXT,
            ema20               REAL,
            ema50               REAL,
            atr14               REAL,
            swing_low           REAL,
            reasons             TEXT,
            llm_verdict         TEXT,
            llm_confidence      INTEGER,
            llm_reasoning       TEXT,
            llm_model           TEXT,
            panel_method        TEXT,
            vcp_detected        INTEGER,
            bull_flag_detected  INTEGER,
            pattern_score       INTEGER,
            catalyst_category   TEXT,
            catalyst_summary    TEXT,
            catalyst_source     TEXT,
            catalyst_url        TEXT,
            catalyst_score      INTEGER,
            catalyst_confidence INTEGER,
            catalyst_theme      TEXT,
            catalyst_mapping_source TEXT,
            created_at          {now_default},
            UNIQUE(scan_date, symbol)
        )
    """)
    for col, typedef in [
        ("swing_low", "REAL"),
        ("llm_verdict", "TEXT"),
        ("llm_confidence", "INTEGER"),
        ("llm_reasoning", "TEXT"),
        ("llm_model", "TEXT"),
        ("panel_method", "TEXT"),
        ("vcp_detected", "INTEGER"),
        ("bull_flag_detected", "INTEGER"),
        ("pattern_score", "INTEGER"),
        ("catalyst_category", "TEXT"),
        ("catalyst_summary", "TEXT"),
        ("catalyst_source", "TEXT"),
        ("catalyst_url", "TEXT"),
        ("catalyst_score", "INTEGER"),
        ("catalyst_confidence", "INTEGER"),
        ("catalyst_theme", "TEXT"),
        ("catalyst_mapping_source", "TEXT"),
    ]:
        _add_column(conn, T_BREAKOUT_LOG, col, typedef)

    execute(conn, f"""
        CREATE TABLE IF NOT EXISTS {T_LLM_EVALUATIONS} (
            id             {id_type} PRIMARY KEY,
            scan_date      TEXT NOT NULL,
            symbol         TEXT NOT NULL,
            panel_method   TEXT NOT NULL,
            llm_model      TEXT NOT NULL,
            verdict        TEXT NOT NULL,
            confidence     INTEGER,
            reasoning      TEXT,
            created_at     {now_default},
            updated_at     {now_default},
            UNIQUE(scan_date, symbol, panel_method, llm_model)
        )
    """)
    execute(conn, f"""
        CREATE INDEX IF NOT EXISTS idx_llm_eval_symbol_date
        ON {T_LLM_EVALUATIONS}(symbol, scan_date)
    """)
    execute(conn, f"""
        INSERT INTO {T_LLM_EVALUATIONS}
            (scan_date, symbol, panel_method, llm_model, verdict, confidence, reasoning)
        SELECT scan_date, symbol,
               COALESCE(NULLIF(panel_method, ''), 'LEGACY'),
               COALESCE(NULLIF(llm_model, ''), 'legacy'),
               llm_verdict, llm_confidence, llm_reasoning
        FROM {T_BREAKOUT_LOG}
        WHERE llm_verdict IS NOT NULL
          AND llm_verdict NOT IN ('', 'SKIPPED')
        ON CONFLICT(scan_date, symbol, panel_method, llm_model) DO NOTHING
    """)

    execute(conn, f"""
        CREATE TABLE IF NOT EXISTS {T_CATALYST_EVENTS} (
            id             {id_type} PRIMARY KEY,
            event_date     TEXT NOT NULL,
            symbol         TEXT NOT NULL,
            source         TEXT NOT NULL,
            category       TEXT NOT NULL,
            title          TEXT NOT NULL,
            summary        TEXT,
            url            TEXT,
            score          INTEGER DEFAULT 0,
            confidence     INTEGER DEFAULT 0,
            theme          TEXT,
            mapping_source TEXT,
            raw_payload    TEXT,
            fetched_at     {now_default},
            UNIQUE(event_date, symbol, source, title)
        )
    """)
    for col, typedef in [
        ("confidence", "INTEGER DEFAULT 0"),
        ("theme", "TEXT"),
        ("mapping_source", "TEXT"),
    ]:
        _add_column(conn, T_CATALYST_EVENTS, col, typedef)
    execute(conn, f"""
        CREATE INDEX IF NOT EXISTS idx_catalyst_symbol_date
        ON {T_CATALYST_EVENTS}(symbol, event_date)
    """)

    execute(conn, f"""
        CREATE TABLE IF NOT EXISTS {T_INVALID_INSTRUMENTS} (
            symbol   TEXT PRIMARY KEY,
            reason   TEXT NOT NULL,
            source   TEXT NOT NULL,
            added_at {now_default}
        )
    """)

    conn.commit()
    conn.close()
    print("[DB] Tables initialized.")


def save_signal(symbol, signal_type, price, reason):
    conn = get_conn()
    execute(
        conn,
        f"INSERT INTO {T_SIGNALS} (symbol, signal_date, signal_type, price, reason) VALUES (?,?,?,?,?)",
        (symbol, str(date.today()), signal_type, price, reason),
    )
    conn.commit()
    conn.close()


def open_position(symbol, buy_price, target_price, stop_loss_price, trailing_stop_price=None):
    conn = get_conn()
    trail = trailing_stop_price if trailing_stop_price is not None else stop_loss_price
    try:
        execute(conn, f"""
            INSERT INTO {T_POSITIONS}
                (symbol, buy_date, buy_price, target_price, stop_loss_price, trailing_stop_price)
            VALUES (?,?,?,?,?,?)
        """, (symbol, str(date.today()), buy_price, target_price, stop_loss_price, trail))
        conn.commit()
    except integrity_error_types():
        conn.rollback()
    conn.close()


def reset_positions():
    conn = get_conn()
    execute(conn, f"DELETE FROM {T_POSITIONS}")
    conn.commit()
    conn.close()
    print("Cleared all old positions!")


def update_trailing_stop(symbol: str, new_trail: float):
    conn = get_conn()
    execute(conn, f"""
        UPDATE {T_POSITIONS}
        SET trailing_stop_price = ?
        WHERE symbol = ?
          AND status = 'OPEN'
          AND (trailing_stop_price IS NULL OR trailing_stop_price < ?)
    """, (new_trail, symbol, new_trail))
    conn.commit()
    conn.close()


def get_open_positions() -> list:
    conn = get_conn()
    rows = execute(conn, f"SELECT * FROM {T_POSITIONS} WHERE status='OPEN'").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def close_position(symbol, exit_price, pnl_pct):
    conn = get_conn()
    execute(conn, f"""
        UPDATE {T_POSITIONS}
        SET status='CLOSED', exit_price=?, exit_date=?, pnl_pct=?
        WHERE symbol=? AND status='OPEN'
    """, (exit_price, str(date.today()), pnl_pct, symbol))
    conn.commit()
    conn.close()


def get_llm_verdict_cache(scan_date: str, panel_method: str | None = None, llm_model: str | None = None) -> dict:
    conn = get_conn()
    sql = f"""
        SELECT symbol, verdict, confidence, reasoning, panel_method, llm_model
        FROM {T_LLM_EVALUATIONS}
        WHERE scan_date = ?
          AND verdict NOT IN ('SKIPPED', '')
          AND verdict IS NOT NULL
    """
    params = [scan_date]
    if panel_method:
        sql += " AND panel_method = ?"
        params.append(panel_method)
    if llm_model:
        sql += " AND llm_model = ?"
        params.append(llm_model)
    rows = execute(conn, sql, params).fetchall()
    conn.close()
    return {
        r["symbol"]: {
            "llm_verdict": r["verdict"],
            "llm_confidence": r["confidence"],
            "llm_reasoning": r["reasoning"],
            "panel_method": r["panel_method"],
            "llm_model": r["llm_model"],
        }
        for r in rows
    }


def _breakout_log_row(scan_date: str, sig: dict) -> tuple:
    return (
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
        sig.get("catalyst_category"),
        sig.get("catalyst_summary"),
        sig.get("catalyst_source"),
        sig.get("catalyst_url"),
        sig.get("catalyst_score"),
        sig.get("catalyst_confidence"),
        sig.get("catalyst_theme"),
        sig.get("catalyst_mapping_source"),
    )


def _llm_evaluation_row(scan_date: str, sig: dict) -> tuple | None:
    verdict = sig.get("llm_verdict")
    panel_method = sig.get("panel_method")
    llm_model = sig.get("llm_model")
    if not (verdict and verdict not in ("", "SKIPPED") and panel_method and llm_model):
        return None
    return (
        scan_date,
        sig.get("symbol"),
        panel_method,
        llm_model,
        verdict,
        sig.get("llm_confidence"),
        sig.get("llm_reasoning"),
    )


def _chunks(rows: list[tuple], size: int = DB_WRITE_BATCH_SIZE):
    for start in range(0, len(rows), size):
        yield rows[start:start + size]


def save_breakout_logs(scan_date: str, signals: list[dict]) -> int:
    if not signals:
        return 0
    conn = get_conn()
    insert_target = f"{T_BREAKOUT_LOG} AS existing" if is_postgres() else T_BREAKOUT_LOG
    existing = "existing." if is_postgres() else ""
    breakout_sql = f"""
        INSERT INTO {insert_target}
            (scan_date, symbol, signal_type, close, rsi, vol_ratio, score,
             stage, ema20, ema50, atr14, swing_low, reasons,
             llm_verdict, llm_confidence, llm_reasoning,
             panel_method, llm_model, vcp_detected, bull_flag_detected, pattern_score,
             catalyst_category, catalyst_summary, catalyst_source, catalyst_url,
             catalyst_score, catalyst_confidence, catalyst_theme, catalyst_mapping_source)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                WHEN {existing}llm_verdict IS NULL OR {existing}llm_verdict IN ('SKIPPED', '') THEN excluded.llm_verdict
                ELSE {existing}llm_verdict
            END,
            llm_confidence = CASE
                WHEN excluded.llm_verdict NOT IN ('SKIPPED', '') THEN excluded.llm_confidence
                WHEN {existing}llm_verdict IS NULL OR {existing}llm_verdict IN ('SKIPPED', '') THEN excluded.llm_confidence
                ELSE {existing}llm_confidence
            END,
            llm_reasoning = CASE
                WHEN excluded.llm_verdict NOT IN ('SKIPPED', '') THEN excluded.llm_reasoning
                WHEN {existing}llm_verdict IS NULL OR {existing}llm_verdict IN ('SKIPPED', '') THEN excluded.llm_reasoning
                ELSE {existing}llm_reasoning
            END,
            panel_method = CASE
                WHEN excluded.llm_verdict NOT IN ('SKIPPED', '') THEN excluded.panel_method
                WHEN {existing}llm_verdict IS NULL OR {existing}llm_verdict IN ('SKIPPED', '') THEN excluded.panel_method
                ELSE {existing}panel_method
            END,
            llm_model = CASE
                WHEN excluded.llm_verdict NOT IN ('SKIPPED', '') THEN excluded.llm_model
                WHEN {existing}llm_verdict IS NULL OR {existing}llm_verdict IN ('SKIPPED', '') THEN excluded.llm_model
                ELSE {existing}llm_model
            END,
            vcp_detected       = COALESCE(excluded.vcp_detected, {existing}vcp_detected),
            bull_flag_detected = COALESCE(excluded.bull_flag_detected, {existing}bull_flag_detected),
            pattern_score      = COALESCE(excluded.pattern_score, {existing}pattern_score),
            catalyst_category  = COALESCE(excluded.catalyst_category, {existing}catalyst_category),
            catalyst_summary   = COALESCE(excluded.catalyst_summary, {existing}catalyst_summary),
            catalyst_source    = COALESCE(excluded.catalyst_source, {existing}catalyst_source),
            catalyst_url       = COALESCE(excluded.catalyst_url, {existing}catalyst_url),
            catalyst_score     = COALESCE(excluded.catalyst_score, {existing}catalyst_score),
            catalyst_confidence = COALESCE(excluded.catalyst_confidence, {existing}catalyst_confidence),
            catalyst_theme     = COALESCE(excluded.catalyst_theme, {existing}catalyst_theme),
            catalyst_mapping_source = COALESCE(excluded.catalyst_mapping_source, {existing}catalyst_mapping_source)
    """
    breakout_rows = [_breakout_log_row(scan_date, sig) for sig in signals]
    for chunk in _chunks(breakout_rows):
        executemany(conn, breakout_sql, chunk)

    llm_rows = [
        row for row in (_llm_evaluation_row(scan_date, sig) for sig in signals)
        if row is not None
    ]
    if llm_rows:
        llm_sql = f"""
            INSERT INTO {T_LLM_EVALUATIONS}
                (scan_date, symbol, panel_method, llm_model, verdict,
                 confidence, reasoning, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(scan_date, symbol, panel_method, llm_model) DO UPDATE SET
                verdict=excluded.verdict,
                confidence=excluded.confidence,
                reasoning=excluded.reasoning,
                updated_at=excluded.updated_at
        """
        for chunk in _chunks(llm_rows):
            executemany(conn, llm_sql, chunk)
    conn.commit()
    conn.close()
    return len(signals)


def save_breakout_log(scan_date: str, sig: dict):
    save_breakout_logs(scan_date, [sig])


def save_catalyst_events(events: list[dict]) -> int:
    if not events:
        return 0
    rows = []
    for event in events:
        rows.append((
            event.get("event_date"),
            event.get("symbol"),
            event.get("source"),
            event.get("category"),
            event.get("title"),
            event.get("summary"),
            event.get("url"),
            event.get("score", 0),
            event.get("confidence", 0),
            event.get("theme"),
            event.get("mapping_source"),
            event.get("raw_payload"),
        ))
    conn = get_conn()
    before = getattr(conn, "total_changes", 0)
    executemany(conn, f"""
        INSERT INTO {T_CATALYST_EVENTS}
            (event_date, symbol, source, category, title, summary, url,
             score, confidence, theme, mapping_source, raw_payload)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(event_date, symbol, source, title) DO UPDATE SET
            category=excluded.category,
            summary=excluded.summary,
            url=excluded.url,
            score=excluded.score,
            confidence=excluded.confidence,
            theme=excluded.theme,
            mapping_source=excluded.mapping_source,
            raw_payload=excluded.raw_payload,
            fetched_at=datetime('now')
    """, rows)
    conn.commit()
    if is_postgres():
        changed = len(rows)
    else:
        changed = getattr(conn, "total_changes", 0) - before
    conn.close()
    return changed


def get_catalyst_events(upto_date: str, lookback_days: int = 7, min_score: int = 0) -> list[dict]:
    cutoff = (date.fromisoformat(upto_date) - timedelta(days=lookback_days)).isoformat()
    conn = get_conn()
    rows = execute(conn, f"""
        SELECT event_date, symbol, source, category, title, summary, url,
               score, confidence, theme, mapping_source
        FROM {T_CATALYST_EVENTS}
        WHERE event_date >= ?
          AND event_date <= ?
          AND score >= ?
        ORDER BY score DESC, event_date DESC
    """, (cutoff, upto_date, min_score)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_invalid_instrument(symbol: str, reason: str, source: str) -> None:
    conn = get_conn()
    execute(conn, f"""
        INSERT INTO {T_INVALID_INSTRUMENTS} (symbol, reason, source)
        VALUES (?, ?, ?)
        ON CONFLICT(symbol) DO NOTHING
    """, (symbol, reason, source))
    conn.commit()
    conn.close()


def bulk_add_invalid_instruments(rows: list) -> int:
    if not rows:
        return 0
    params = [(row["symbol"], row["reason"], row["source"]) for row in rows]
    conn = get_conn()
    before = getattr(conn, "total_changes", 0)
    executemany(conn, f"""
        INSERT INTO {T_INVALID_INSTRUMENTS} (symbol, reason, source)
        VALUES (?, ?, ?)
        ON CONFLICT(symbol) DO NOTHING
    """, params)
    conn.commit()
    added = len(params) if is_postgres() else getattr(conn, "total_changes", 0) - before
    conn.close()
    return added


def get_invalid_symbols() -> set:
    conn = get_conn()
    rows = execute(conn, f"SELECT symbol FROM {T_INVALID_INSTRUMENTS}").fetchall()
    conn.close()
    return {r["symbol"] for r in rows}


def get_breakout_log(days: int = 30) -> pd.DataFrame:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    conn = get_conn()
    df = read_dataframe(conn, f"""
        WITH latest_eval AS (
            SELECT *
            FROM {T_LLM_EVALUATIONS}
            WHERE id IN (
                SELECT MAX(id)
                FROM {T_LLM_EVALUATIONS}
                GROUP BY scan_date, symbol
            )
        )
        SELECT b.scan_date, b.symbol, b.signal_type, b.close, b.rsi,
               b.vol_ratio, b.score, b.stage, b.ema20, b.ema50, b.atr14,
               b.reasons,
               COALESCE(le.verdict, b.llm_verdict) AS llm_verdict,
               COALESCE(le.confidence, b.llm_confidence) AS llm_confidence,
               COALESCE(le.reasoning, b.llm_reasoning) AS llm_reasoning,
               COALESCE(le.panel_method, b.panel_method) AS panel_method,
               COALESCE(le.llm_model, b.llm_model) AS llm_model,
               b.created_at
        FROM {T_BREAKOUT_LOG} b
        LEFT JOIN latest_eval le
          ON le.scan_date = b.scan_date
         AND le.symbol = b.symbol
        WHERE b.scan_date >= ?
        ORDER BY b.scan_date DESC, b.score DESC
    """, (cutoff,))
    conn.close()
    return df


def delete_breakout_log(scan_date: str) -> int:
    conn = get_conn()
    execute(conn, f"DELETE FROM {T_LLM_EVALUATIONS} WHERE scan_date = ?", (scan_date,))
    cur = execute(conn, f"DELETE FROM {T_BREAKOUT_LOG} WHERE scan_date = ?", (scan_date,))
    deleted = getattr(cur, "rowcount", 0)
    conn.commit()
    conn.close()
    return deleted
