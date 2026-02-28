
# ============================================================
# agent/portfolio_tracker.py – Track open positions and exits
# ============================================================
from data.database      import (get_open_positions, close_position,
                                 save_signal, update_trailing_stop)
from data.upstox_client import fetch_historical, fetch_ltp
from analysis.technical import add_indicators
from config import (PROFIT_TARGET_PCT, STOP_LOSS_PCT,
                    MAX_HOLD_DAYS, ATR_TRAIL_MULTIPLIER)
from datetime import date, datetime
from tabulate import tabulate
import pandas as pd


def _get_current_price(symbol: str, ltp_cache: dict) -> float | None:
    """
    Return the most up-to-date price for a symbol.
    1. Try the LTP cache (live/EOD from Upstox market-quote API).
    2. Fall back to the last row of the historical candle data.
    """
    if symbol in ltp_cache:
        return ltp_cache[symbol]
    # Fallback: last close from historical API
    df = fetch_historical(symbol)
    if not df.empty:
        return float(df["close"].iloc[-1])
    return None


def check_exit_signals():
    """
    For each open position check three exit conditions (in priority order):
    1. PROFIT TARGET  – price reached fixed ceiling (+PROFIT_TARGET_PCT %)
    2. TRAILING STOP  – price fell through the ATR-ratcheted trailing stop
    3. TIME EXIT      – held longer than MAX_HOLD_DAYS

    The trailing stop is ratcheted up each run:
        new_trail = current_price − ATR_TRAIL_MULTIPLIER × ATR14
    It is only ever moved UP (database enforces this).
    """
    positions = get_open_positions()
    exits = []

    if not positions:
        return exits

    # ── Batch-fetch live prices for all open positions upfront ───────────
    symbols   = [p["symbol"] for p in positions]
    ltp_cache = fetch_ltp(symbols)
    if ltp_cache:
        print(f"  [LTP] Live prices fetched for {len(ltp_cache)}/{len(symbols)} symbols.")
    else:
        print("  [LTP] Market closed or LTP unavailable – using last historical close.")

    for pos in positions:
        symbol    = pos["symbol"]
        buy_price = pos["buy_price"]
        buy_date  = datetime.strptime(pos["buy_date"], "%Y-%m-%d").date()
        days_held = (date.today() - buy_date).days

        current_price = _get_current_price(symbol, ltp_cache)
        if current_price is None:
            print(f"  [WARN] Could not get price for {symbol}, skipping.")
            continue

        pnl_pct = (current_price - buy_price) / buy_price * 100

        # ── Compute ATR14 from latest historical data (always needed for trailing stop) ─
        df_ind = fetch_historical(symbol)
        atr14  = None
        if not df_ind.empty:
            df_ind = add_indicators(df_ind)
            atr_val = df_ind["atr14"].iloc[-1]
            atr14   = float(atr_val) if atr_val is not None and not pd.isna(atr_val) else None

        # ── Ratchet trailing stop upward ────────────────────────────────────
        if atr14 and atr14 > 0:
            new_trail = round(current_price - ATR_TRAIL_MULTIPLIER * atr14, 2)
            update_trailing_stop(symbol, new_trail)   # DB enforces no downward movement

        # Re-read the (possibly updated) trailing stop from position record
        # Use the stored value; update_trailing_stop already ran its SQL
        trail = pos.get("trailing_stop_price") or pos.get("stop_loss_price")
        if trail is None:
            # Ultimate fallback: percentage-based SL
            trail = round(buy_price * (1 - STOP_LOSS_PCT / 100), 2)

        # Merge with newly-computed new_trail in case DB read is stale
        if atr14 and atr14 > 0:
            trail = max(trail, new_trail)

        # ── Exit decision ────────────────────────────────────────────────────
        target_price = pos.get("target_price")
        reason = None
        if target_price and current_price >= target_price:
            reason = f"TARGET HIT ₹{target_price:.2f} (+{pnl_pct:.1f}%)"
        elif pnl_pct >= PROFIT_TARGET_PCT:
            reason = f"PROFIT TARGET +{pnl_pct:.1f}%"
        elif current_price <= trail:
            reason = f"TRAILING STOP ₹{trail:.2f} (PnL {pnl_pct:+.1f}%)"
        elif days_held >= MAX_HOLD_DAYS:
            reason = f"MAX HOLD {days_held}d PnL={pnl_pct:+.1f}%"

        if reason:
            close_position(symbol, current_price, pnl_pct)
            save_signal(symbol, "SELL", current_price, reason)
            exits.append({
                "symbol":     symbol,
                "buy_price":  buy_price,
                "exit_price": current_price,
                "pnl_pct":    round(pnl_pct, 2),
                "reason":     reason,
            })
            print(f"[EXIT] {symbol} @ ₹{current_price:.2f}  {reason}")

    return exits


def print_portfolio():
    positions = get_open_positions()
    if not positions:
        print("No open positions.")
        return

    # Batch-fetch live LTP for all positions in one API call
    symbols   = [pos["symbol"] for pos in positions]
    ltp_cache = fetch_ltp(symbols)
    market_status = "LIVE" if ltp_cache else "CLOSED (last close)"

    rows = []
    for pos in positions:
        cmp = _get_current_price(pos["symbol"], ltp_cache)
        if cmp is None:
            cmp = pos["buy_price"]   # last resort
        pnl   = (cmp - pos["buy_price"]) / pos["buy_price"] * 100
        trail = pos.get("trailing_stop_price") or pos.get("stop_loss_price") or "-"
        pnl_str = f"{pnl:+.2f}%"
        rows.append([
            pos["symbol"],
            f"₹{pos['buy_price']:.2f}",
            f"₹{cmp:.2f}",
            pnl_str,
            pos["buy_date"],
            f"₹{pos['target_price']:.2f}",
            f"₹{pos['stop_loss_price']:.2f}",
            f"₹{trail:.2f}" if isinstance(trail, float) else trail,
        ])

    headers = ["Symbol", "Buy", f"CMP ({market_status})", "PnL%",
               "Date", "Target", "Init SL", "Trail SL"]
    print("\n" + tabulate(rows, headers=headers, tablefmt="fancy_grid"))
