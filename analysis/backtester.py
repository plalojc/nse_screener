"""
analysis/backtester.py
======================
Backtesting engine - validates past breakout signals against real subsequent price action.

Usage
-----
    from analysis.backtester import run_backtest
    results = run_backtest("2026-02-01", forward_days=30)

How it works
------------
1.  All symbols in the local DB that have OHLCV data on or before *signal_date* are loaded.
2.  Each symbol's history is **capped at signal_date** (no future leakage).
3.  The same breakout + pullback scanners used in the live scan are run on the capped data.
4.  For every signal found, SL and 2R target are computed with the exact same logic as the
    live screener.
5.  Forward candles (from signal_date+1 to signal_date+forward_days) are loaded from the DB.
6.  Each forward trading day is walked:
      - intraday HIGH >= target  -> WIN  (triggered on that day)
      - intraday LOW  <= SL      -> LOSS (triggered on that day)
      - neither within window    -> OPEN
7.  Additional stats recorded per signal:
      max_gain_pct  - best intraday high vs entry, as %
      max_dd_pct    - worst intraday low vs entry, as %  (negative = drawdown)
      final_pct     - % change of last available close vs entry

Returns
-------
A list of result dicts, one per signal, with all original signal fields plus:
    signal_date, forward_days, entry_price, target_price, stop_loss,
    outcome (WIN|LOSS|OPEN), outcome_day, max_gain_pct, max_dd_pct,
    final_pct, forward_close, fwd_candles_available
"""

from __future__ import annotations

from datetime import datetime, timedelta

from analysis.breakout_scanner import is_breakout, is_ma_pullback
from config import ATR_SL_MULTIPLIER, STOP_LOSS_PCT
from data.nse_bhavcopy_client import (
    get_symbols_with_data_upto,
    load_ohlcv_upto,
    load_ohlcv_range,
)


# == Public API ================================================================

def run_backtest(signal_date: str, forward_days: int = 30) -> list[dict]:
    """
    Run the screener on *signal_date* using cached NSE Bhavcopy data, then evaluate
    each signal against the next *forward_days* calendar days of OHLCV data.

    Parameters
    ----------
    signal_date  : str  - "YYYY-MM-DD"
    forward_days : int  - how many calendar days forward to look for outcome

    Returns
    -------
    list of result dicts (may be empty if no signals or insufficient data)
    """
    end_date = (
        datetime.strptime(signal_date, "%Y-%m-%d") + timedelta(days=forward_days)
    ).strftime("%Y-%m-%d")

    symbols = get_symbols_with_data_upto(signal_date)
    total   = len(symbols)

    if total == 0:
        print(f"  [WARN] No NSE Bhavcopy data found for date <= {signal_date}.")
        print(  "         Run a scan first to populate the Bhavcopy cache.")
        return []

    print(f"  {total} symbols in DB with data up to {signal_date}")
    print(f"  Scanning for signals on {signal_date} -> evaluating until {end_date} ...\n")

    results = []

    for i, symbol in enumerate(symbols, 1):
        print(f"\r  [{i:>4}/{total}] {symbol:<20}", end="", flush=True)

        # == 1. Load history capped at signal_date (no future leakage) ========
        df = load_ohlcv_upto(symbol, signal_date)
        if len(df) < 30:          # is_breakout needs >=30; is_ma_pullback needs >=60 (self-checked)
            continue

        # == 2. Detect signals using the same scanners as the live screener ==
        #    Run BOTH scanners (mirrors screener_agent.py which collects all
        #    signals in a loop - a symbol can produce BREAKOUT + PULLBACK).
        sigs_found = []
        for scanner in (is_breakout, is_ma_pullback):
            sig = scanner(df)
            if sig is not None:
                sigs_found.append(sig)

        if not sigs_found:
            continue

        # == 4. Load forward candles (shared for all signals on this symbol) ==
        fwd = load_ohlcv_range(symbol, signal_date, end_date)

        for sig in sigs_found:
            # == 3. Compute SL and 2R target (mirrors screener_agent.py) =====
            bp  = sig["close"]
            atr = sig.get("atr14") or 0

            sl_atr   = round(bp - ATR_SL_MULTIPLIER * atr, 2) if atr > 0 else None
            sl_swing = round(sig["swing_low"] * 0.99, 2) if sig.get("swing_low") else None
            cands    = [x for x in [sl_atr, sl_swing] if x is not None and x < bp]
            sl       = max(cands) if cands else round(bp * (1 - STOP_LOSS_PCT / 100), 2)
            risk     = bp - sl
            tp       = round(bp + risk * 2, 2)

            # == 5. Walk forward day-by-day ====================================
            outcome     = "OPEN"
            outcome_day = None
            max_high    = bp     # track best intraday high
            min_low     = bp     # track worst intraday low

            for day_idx, (_, row) in enumerate(fwd.iterrows(), 1):
                h = float(row["high"])
                l = float(row["low"])

                if h > max_high:
                    max_high = h
                if l < min_low:
                    min_low = l

                if h >= tp:                   # target hit (intraday high reached / exceeded)
                    outcome     = "WIN"
                    outcome_day = day_idx
                    break
                if l <= sl:                   # stop loss hit (intraday low broke through SL)
                    outcome     = "LOSS"
                    outcome_day = day_idx
                    break

            forward_close = float(fwd.iloc[-1]["close"]) if not fwd.empty else bp
            max_gain_pct  = round((max_high    - bp) / bp * 100, 2)
            max_dd_pct    = round((min_low     - bp) / bp * 100, 2)
            final_pct     = round((forward_close - bp) / bp * 100, 2)

            results.append({
                **sig,
                "signal_date":           signal_date,
                "forward_days":          forward_days,
                "entry_price":           bp,
                "target_price":          tp,
                "stop_loss":             sl,
                "outcome":               outcome,
                "outcome_day":           outcome_day,
                "max_gain_pct":          max_gain_pct,
                "max_dd_pct":            max_dd_pct,
                "final_pct":             final_pct,
                "forward_close":         forward_close,
                "fwd_candles_available": len(fwd),
            })

    print()   # newline after progress bar
    return results
