
# ============================================================
# agent/backtester.py – Backtest & Forward Validation
# ============================================================
# Validates historical breakout signals by simulating trades
# using actual forward price data.
#
# Usage:
#   python main.py backtest --date 2026-02-01
#
# Workflow:
#   1. Load signals for scan_date from breakout_log (or run fresh scan)
#   2. Fetch forward OHLCV data for each signal (scan_date → today)
#   3. Simulate trades: entry at signal close, check SL/TP/trailing/max-hold
#   4. Generate validation HTML report with LLM accuracy breakdown
# ============================================================

import sqlite3
import pandas as pd
from datetime import date, datetime, timedelta
from colorama import Fore, Style, init

from data.database import get_conn, init_db
from data.upstox_client import fetch_historical
from config import (
    ATR_SL_MULTIPLIER, ATR_TRAIL_MULTIPLIER,
    STOP_LOSS_PCT, PROFIT_TARGET_PCT, MAX_HOLD_DAYS,
    REPORT_DIR,
)

init(autoreset=True)


# ── Signal Loading ──────────────────────────────────────────────────────────────

def _load_signals_for_date(scan_date: str) -> list:
    """
    Load breakout signals for a specific scan_date from breakout_log.
    Returns list of signal dicts, or empty list if none found.
    """
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT symbol, signal_type, close, rsi, vol_ratio, score,
               stage, ema20, ema50, atr14, swing_low, reasons,
               llm_verdict, llm_confidence, llm_reasoning,
               tech_verdict, tech_confidence, sent_verdict, sent_confidence,
               risk_verdict, risk_confidence,
               live_verdict, live_confidence, live_reasoning,
               panel_method, vcp_detected, bull_flag_detected
        FROM   breakout_log
        WHERE  scan_date = ?
        ORDER  BY score DESC
        """,
        (scan_date,),
    ).fetchall()
    conn.close()

    signals = []
    for r in rows:
        signals.append({
            "symbol":           r["symbol"],
            "signal_type":      r["signal_type"],
            "close":            r["close"],
            "rsi":              r["rsi"],
            "vol_ratio":        r["vol_ratio"],
            "score":            r["score"],
            "stage":            r["stage"],
            "ema20":            r["ema20"],
            "ema50":            r["ema50"],
            "atr14":            r["atr14"],
            "swing_low":        r["swing_low"],
            "reasons":          r["reasons"],
            "llm_verdict":      r["llm_verdict"],
            "llm_confidence":   r["llm_confidence"],
            "llm_reasoning":    r["llm_reasoning"],
            "tech_verdict":     r["tech_verdict"],
            "tech_confidence":  r["tech_confidence"],
            "sent_verdict":     r["sent_verdict"],
            "sent_confidence":  r["sent_confidence"],
            "risk_verdict":     r["risk_verdict"],
            "risk_confidence":  r["risk_confidence"],
            "live_verdict":     r["live_verdict"],
            "live_confidence":  r["live_confidence"],
            "live_reasoning":   r["live_reasoning"],
            "panel_method":     r["panel_method"],
            "vcp_detected":     r["vcp_detected"],
            "bull_flag_detected": r["bull_flag_detected"],
        })
    return signals


# ── SL / TP Calculation (same logic as screener_agent.py) ───────────────────────

def _calc_sl_tp(sig: dict):
    """
    Calculate stop-loss and target price for a signal.
    Uses the exact same logic as screener_agent.py lines 262-272.
    Returns (sl, tp, sl_method)
    """
    bp  = sig["close"]
    atr = sig.get("atr14") or 0

    sl_atr   = round(bp - ATR_SL_MULTIPLIER * atr, 2) if atr > 0 else None
    sl_swing = round(sig["swing_low"] * 0.99, 2) if sig.get("swing_low") else None
    candidates = [x for x in [sl_atr, sl_swing] if x is not None and x < bp]
    sl = max(candidates) if candidates else round(bp * (1 - STOP_LOSS_PCT / 100), 2)

    risk = bp - sl
    tp   = round(bp + risk * 2, 2)  # 2:1 reward-to-risk
    sl_method = ("ATR" if sl == sl_atr else "SwingLow" if sl == sl_swing else "Fixed%")

    return sl, tp, sl_method


# ── Trade Simulation ────────────────────────────────────────────────────────────

def _simulate_trade(sig: dict, forward_df: pd.DataFrame, scan_date: str) -> dict:
    """
    Simulate a trade by walking forward through candles after entry.

    Entry: close price on scan_date.
    Exit checks (each day, in priority order):
      1. Stop loss:   candle.low <= trailing_stop → exit at trailing_stop
      2. Target:      candle.high >= target → exit at target
      3. Max hold:    days_held >= MAX_HOLD_DAYS → exit at candle.close
      4. End of data: still holding → OPEN with unrealized PnL

    Returns dict with trade results.
    """
    entry_price = sig["close"]
    sl, tp, sl_method = _calc_sl_tp(sig)
    atr = sig.get("atr14") or 0
    trailing_stop = sl

    # Track metrics
    max_price     = entry_price
    min_price     = entry_price
    exit_price    = None
    exit_date     = None
    exit_reason   = None
    hold_days     = 0

    # Filter forward data: only candles AFTER scan_date
    fwd = forward_df[forward_df["date"] > scan_date].copy()
    fwd = fwd.sort_values("date").reset_index(drop=True)

    for _, candle in fwd.iterrows():
        hold_days += 1

        candle_high  = float(candle["high"])
        candle_low   = float(candle["low"])
        candle_close = float(candle["close"])
        candle_date  = str(candle["date"])

        # Track max/min for gain/drawdown
        max_price = max(max_price, candle_high)
        min_price = min(min_price, candle_low)

        # 1. Stop loss hit (intraday low touches or breaks trailing stop)
        if candle_low <= trailing_stop:
            exit_price  = trailing_stop
            exit_date   = candle_date
            exit_reason = "SL HIT"
            break

        # 2. Target hit (intraday high reaches target)
        if candle_high >= tp:
            exit_price  = tp
            exit_date   = candle_date
            exit_reason = "TARGET HIT"
            break

        # 3. Max hold days exceeded
        if hold_days >= MAX_HOLD_DAYS:
            exit_price  = candle_close
            exit_date   = candle_date
            exit_reason = "TIME EXIT"
            break

        # Ratchet trailing stop upward (only if ATR available)
        if atr > 0:
            new_trail = round(candle_close - ATR_TRAIL_MULTIPLIER * atr, 2)
            trailing_stop = max(trailing_stop, new_trail)

    # If we ran out of candles without exiting → still OPEN
    if exit_price is None:
        if not fwd.empty:
            exit_price = float(fwd.iloc[-1]["close"])
            exit_date  = str(fwd.iloc[-1]["date"])
        else:
            exit_price = entry_price
            exit_date  = scan_date
        exit_reason = "OPEN"
        hold_days = max(hold_days, 1)

    pnl_pct = round((exit_price - entry_price) / entry_price * 100, 2)
    max_gain_pct = round((max_price - entry_price) / entry_price * 100, 2)
    max_dd_pct   = round((entry_price - min_price) / entry_price * 100, 2)

    return {
        "symbol":       sig["symbol"],
        "signal_type":  sig.get("signal_type", "BREAKOUT"),
        "entry_price":  entry_price,
        "entry_date":   scan_date,
        "sl_price":     sl,
        "tp_price":     tp,
        "sl_method":    sl_method,
        "exit_price":   round(exit_price, 2),
        "exit_date":    exit_date,
        "pnl_pct":      pnl_pct,
        "hold_days":    hold_days,
        "exit_reason":  exit_reason,
        "max_gain_pct": max_gain_pct,
        "max_dd_pct":   max_dd_pct,
        # Carry forward signal metadata for report
        "score":           sig.get("score", 0),
        "rsi":             sig.get("rsi"),
        "vol_ratio":       sig.get("vol_ratio"),
        "stage":           sig.get("stage"),
        "llm_verdict":     sig.get("llm_verdict"),
        "llm_confidence":  sig.get("llm_confidence"),
        "llm_reasoning":   sig.get("llm_reasoning"),
        "live_verdict":    sig.get("live_verdict"),
        "live_confidence": sig.get("live_confidence"),
        "vcp_detected":    sig.get("vcp_detected"),
        "bull_flag_detected": sig.get("bull_flag_detected"),
    }


# ── Stats Aggregation ──────────────────────────────────────────────────────────

def _compute_stats(trades: list, scan_date: str, eval_date: str) -> dict:
    """Compute summary statistics and LLM accuracy breakdown."""
    closed = [t for t in trades if t["exit_reason"] != "OPEN"]
    still_open = [t for t in trades if t["exit_reason"] == "OPEN"]

    all_pnl = [t["pnl_pct"] for t in trades]
    closed_pnl = [t["pnl_pct"] for t in closed]
    winners = [t for t in closed if t["pnl_pct"] > 0]
    losers  = [t for t in closed if t["pnl_pct"] <= 0]

    total = len(trades)
    win_count = len(winners)
    lose_count = len(losers)

    # LLM accuracy breakdown
    by_verdict = {}
    for verdict in ("CONFIRM", "WEAK", "REJECT", "SKIPPED"):
        v_trades = [t for t in trades if (t.get("llm_verdict") or "SKIPPED") == verdict]
        if not v_trades:
            continue
        v_closed = [t for t in v_trades if t["exit_reason"] != "OPEN"]
        v_winners = [t for t in v_closed if t["pnl_pct"] > 0]
        v_pnl = [t["pnl_pct"] for t in v_trades]
        by_verdict[verdict] = {
            "count":      len(v_trades),
            "closed":     len(v_closed),
            "winners":    len(v_winners),
            "win_rate":   round(len(v_winners) / len(v_closed) * 100, 1) if v_closed else 0,
            "avg_return":  round(sum(v_pnl) / len(v_pnl), 2) if v_pnl else 0,
        }

    best  = max(trades, key=lambda t: t["pnl_pct"]) if trades else None
    worst = min(trades, key=lambda t: t["pnl_pct"]) if trades else None

    return {
        "scan_date":       scan_date,
        "eval_date":       eval_date,
        "total_signals":   total,
        "total_closed":    len(closed),
        "winners":         win_count,
        "losers":          lose_count,
        "still_open":      len(still_open),
        "win_rate":        round(win_count / len(closed) * 100, 1) if closed else 0,
        "avg_return_pct":  round(sum(all_pnl) / len(all_pnl), 2) if all_pnl else 0,
        "total_return_pct": round(sum(all_pnl), 2),
        "best_trade":      {"symbol": best["symbol"], "pnl": best["pnl_pct"]} if best else None,
        "worst_trade":     {"symbol": worst["symbol"], "pnl": worst["pnl_pct"]} if worst else None,
        "avg_hold_days":   round(sum(t["hold_days"] for t in trades) / total, 1) if total else 0,
        "by_verdict":      by_verdict,
    }


# ── Main Entry Point ───────────────────────────────────────────────────────────

def run_backtest(scan_date: str, force_refresh: bool = False) -> list:
    """
    Run a backtest for a historical scan date.

    1. Load signals from breakout_log (or run fresh scan if not cached)
    2. Fetch forward OHLCV data for each signal
    3. Simulate trades
    4. Print results and generate HTML validation report

    Returns list of trade result dicts.
    """
    eval_date = str(date.today())

    print(Fore.CYAN + "=" * 60)
    print(Fore.CYAN + "   NSE BREAKOUT AGENT – BACKTEST VALIDATION")
    print(Fore.CYAN + "=" * 60)
    print(Fore.CYAN + f"   Scan date : {scan_date}")
    print(Fore.CYAN + f"   Eval date : {eval_date}")

    # Sanity check: scan_date must be in the past
    scan_dt = datetime.strptime(scan_date, "%Y-%m-%d").date()
    if scan_dt >= date.today():
        print(Fore.RED + "\n  ERROR: scan_date must be in the past for backtesting.")
        return []

    # Check forward data coverage
    days_forward = (date.today() - scan_dt).days
    if days_forward > 85:
        print(Fore.YELLOW +
              f"\n  WARNING: scan_date is {days_forward} days ago. "
              f"Forward data may be incomplete (90-day API window).")

    init_db()

    # ── Step 1: Load signals ─────────────────────────────────────────────────
    print(Fore.YELLOW + "\n[1/3] Loading signals for " + scan_date + "...")

    signals = []
    if not force_refresh:
        signals = _load_signals_for_date(scan_date)

    if signals:
        from collections import Counter
        vc = Counter(s.get("llm_verdict", "SKIPPED") for s in signals)
        print(f"  Found {len(signals)} cached signals in breakout_log.")
        parts = []
        for v in ("CONFIRM", "WEAK", "REJECT", "SKIPPED"):
            if vc.get(v, 0) > 0:
                parts.append(f"{v}: {vc[v]}")
        print(f"  ({' | '.join(parts)})")
    else:
        print("  No cached signals found. Running fresh scan...")
        from agent.screener_agent import run_daily_scan
        run_daily_scan(scan_date=scan_date, force_refresh=force_refresh)
        # Reload from DB after scan
        signals = _load_signals_for_date(scan_date)
        if not signals:
            print(Fore.RED + "  No signals generated for this date. Nothing to backtest.")
            return []
        print(f"  Scan complete. {len(signals)} signals generated.")

    # ── Step 2: Simulate trades ──────────────────────────────────────────────
    print(Fore.YELLOW + f"\n[2/3] Simulating trades ({len(signals)} signals)...")

    trades = []
    fetch_errors = 0

    for idx, sig in enumerate(signals, 1):
        symbol = sig["symbol"]

        # Fetch forward OHLCV data (latest 90 days from today)
        try:
            df = fetch_historical(symbol)
        except Exception as e:
            print(f"  [{idx:>3}/{len(signals)}] {symbol:<15} ERROR fetching data: {e}")
            fetch_errors += 1
            continue

        if df.empty:
            print(f"  [{idx:>3}/{len(signals)}] {symbol:<15} No data available")
            fetch_errors += 1
            continue

        # Ensure date column is string for comparison
        df["date"] = df["date"].astype(str)

        # Check if we have forward data
        fwd_rows = df[df["date"] > scan_date]
        if fwd_rows.empty:
            print(f"  [{idx:>3}/{len(signals)}] {symbol:<15} No forward data after {scan_date}")
            fetch_errors += 1
            continue

        # Simulate the trade
        trade = _simulate_trade(sig, df, scan_date)
        trades.append(trade)

        # Print result
        pnl = trade["pnl_pct"]
        if pnl > 0:
            pnl_color = Fore.GREEN
        elif pnl < -3:
            pnl_color = Fore.RED
        else:
            pnl_color = Fore.YELLOW

        reason_color = {
            "TARGET HIT": Fore.GREEN,
            "SL HIT":     Fore.RED,
            "TIME EXIT":  Fore.YELLOW,
            "OPEN":       Fore.CYAN,
        }.get(trade["exit_reason"], "")

        exit_label = ("Current" if trade["exit_reason"] == "OPEN"
                      else "Exit")

        print(
            f"  [{idx:>3}/{len(signals)}] {symbol:<15} "
            f"Entry ₹{trade['entry_price']:<9.2f} -> "
            f"{exit_label} ₹{trade['exit_price']:<9.2f} "
            f"{pnl_color}{pnl:>+6.1f}%{Style.RESET_ALL}  "
            f"{reason_color}{trade['exit_reason']:<11}{Style.RESET_ALL} "
            f"({trade['hold_days']}d)"
        )

    if fetch_errors:
        print(Fore.YELLOW + f"  ({fetch_errors} symbols skipped due to data errors)")

    if not trades:
        print(Fore.RED + "\n  No trades to evaluate. Aborting.")
        return []

    # ── Step 3: Results ──────────────────────────────────────────────────────
    stats = _compute_stats(trades, scan_date, eval_date)

    print(Fore.YELLOW + "\n[3/3] Results")
    _print_summary(stats)

    # ── Generate HTML report ─────────────────────────────────────────────────
    try:
        from report.backtest_report_writer import write_backtest_report
        html_path = write_backtest_report(trades, stats, REPORT_DIR)
        print(Fore.CYAN + f"\n  HTML report -> {html_path}")
    except Exception as exc:
        print(Fore.YELLOW + f"  [WARN] Could not write HTML report: {exc}")

    return trades


# ── Terminal Summary ────────────────────────────────────────────────────────────

def _print_summary(stats: dict):
    """Print the backtest summary to terminal."""
    W = 54
    print(Fore.GREEN + "  " + "=" * W)

    wr = stats["win_rate"]
    wr_color = Fore.GREEN if wr >= 50 else Fore.RED
    print(
        f"  Win Rate  : {wr_color}{wr:.1f}%{Style.RESET_ALL} "
        f"({stats['winners']} / {stats['total_closed']} closed)"
    )
    if stats["still_open"]:
        print(f"  Still Open: {stats['still_open']}")

    avg_r = stats["avg_return_pct"]
    avg_color = Fore.GREEN if avg_r > 0 else Fore.RED
    print(
        f"  Avg Return: {avg_color}{avg_r:+.2f}%{Style.RESET_ALL}"
        f"  |  Total: {stats['total_return_pct']:+.2f}%"
    )

    if stats["best_trade"]:
        print(
            f"  Best      : {stats['best_trade']['symbol']} "
            f"{Fore.GREEN}{stats['best_trade']['pnl']:+.1f}%{Style.RESET_ALL}"
        )
    if stats["worst_trade"]:
        print(
            f"  Worst     : {stats['worst_trade']['symbol']} "
            f"{Fore.RED}{stats['worst_trade']['pnl']:+.1f}%{Style.RESET_ALL}"
        )

    print(f"  Avg Hold  : {stats['avg_hold_days']:.1f} days")

    print(Fore.GREEN + "  " + "-" * W + Style.RESET_ALL)
    print("  LLM Accuracy:")

    for verdict in ("CONFIRM", "WEAK", "REJECT", "SKIPPED"):
        vd = stats["by_verdict"].get(verdict)
        if not vd:
            continue

        v_color = {
            "CONFIRM": Fore.GREEN,
            "WEAK":    Fore.YELLOW,
            "REJECT":  Fore.RED,
            "SKIPPED": Style.RESET_ALL,
        }.get(verdict, "")

        wr_str = f"{vd['win_rate']:.0f}%" if vd["closed"] > 0 else "N/A"
        print(
            f"    {v_color}{verdict:<8}{Style.RESET_ALL}: "
            f"{vd['winners']}/{vd['closed']} won ({wr_str})  "
            f"avg {vd['avg_return']:+.1f}%"
        )

    print(Fore.GREEN + "  " + "=" * W + Style.RESET_ALL)
