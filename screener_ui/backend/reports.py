from __future__ import annotations

from typing import Any

from data.database import T_BREAKOUT_LOG, T_LLM_EVALUATIONS, delete_breakout_log, get_conn
from data.db_backend import execute, read_dataframe
from report.html_report_writer import render as render_html_report
from .user_settings import app_settings


def list_reports() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = execute(conn, f"""
            SELECT scan_date, COUNT(*) AS candidates
            FROM {T_BREAKOUT_LOG}
            GROUP BY scan_date
            ORDER BY scan_date DESC
        """).fetchall()
    return [
        {
            "date": row["scan_date"],
            "kind": "scan",
            "filename": f"NSE-Breakout-{row['scan_date']}.html",
            "candidates": row["candidates"],
        }
        for row in rows
    ]


def load_report_signals(report_date: str) -> list[dict[str, Any]]:
    with get_conn() as conn:
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
                   b.swing_low, b.reasons,
                   COALESCE(le.verdict, b.llm_verdict) AS llm_verdict,
                   COALESCE(le.confidence, b.llm_confidence) AS llm_confidence,
                   COALESCE(le.reasoning, b.llm_reasoning) AS llm_reasoning,
                   COALESCE(le.panel_method, b.panel_method) AS panel_method,
                   COALESCE(le.llm_model, b.llm_model) AS llm_model,
                   b.vcp_detected, b.bull_flag_detected, b.pattern_score,
                   b.created_at
            FROM {T_BREAKOUT_LOG} b
            LEFT JOIN latest_eval le
              ON le.scan_date = b.scan_date
             AND le.symbol = b.symbol
            WHERE b.scan_date = ?
            ORDER BY b.score DESC, b.symbol
        """, (report_date,))
    if df.empty:
        return []
    return df.where(df.notna(), None).to_dict("records")


def report_exists(report_date: str) -> bool:
    with get_conn() as conn:
        row = execute(conn, f"""
            SELECT COUNT(*) AS count
            FROM {T_BREAKOUT_LOG}
            WHERE scan_date = ?
        """, (report_date,)).fetchone()
    return bool(row and row["count"])


def delete_report(report_date: str) -> int:
    return delete_breakout_log(report_date)


def render_report(report_date: str) -> str | None:
    signals = load_report_signals(report_date)
    if not signals:
        return None
    settings = app_settings()
    return render_html_report(
        signals,
        scan_date=report_date,
        raw_total=len(signals),
        tradingview_chart_id=settings["tradingview_chart_id"],
        include_weak=settings["report_include_weak"],
    )
