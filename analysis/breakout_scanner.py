
# ============================================================
# analysis/breakout_scanner.py – Breakout + Pullback signal detection
# ============================================================
import pandas as pd
from analysis.technical import add_indicators, get_stage
from config import (VOLUME_SURGE_FACTOR, RSI_BREAKOUT_MIN,
                    RSI_OVERBOUGHT, MIN_PRICE, MAX_PRICE, ATR_SL_MULTIPLIER)


def find_swing_low(df: pd.DataFrame, lookback: int = 20) -> float | None:
    """
    Return the most recent local low within the last `lookback` bars.
    A local low at index i satisfies: low[i] < low[i-1]  AND  low[i] < low[i+1].
    Returns None if no swing low is found.
    """
    lows = df["low"].values[-lookback:]
    for i in range(len(lows) - 2, 0, -1):
        if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
            return float(lows[i])
    return None


def _sl_from_atr_and_swing(close, atr14, swing_low):
    """Compute the tightest valid stop loss using ATR and/or swing low."""
    sl_atr   = round(close - ATR_SL_MULTIPLIER * atr14, 2) if atr14 else None
    sl_swing = round(swing_low * 0.99, 2)                   if swing_low else None
    candidates = [x for x in [sl_atr, sl_swing] if x is not None and x < close]
    return max(candidates) if candidates else round(close * 0.95, 2)


# ── Breakout Scanner ──────────────────────────────────────────────────────────

def is_breakout(df: pd.DataFrame) -> dict | None:
    """
    Momentum / breakout signal.
    Scoring criteria (higher = more conviction):
      1. 20-day price breakout + 2x volume surge  (+3)  ← upgraded
         OR plain volume surge 1.5x               (+1)
      2. RSI in momentum zone [55–75]             (+2)
      3. Price > EMA20 > EMA50 (trend alignment)  (+2)
      4. MACD histogram crossover                 (+2/+4 if below zero line)  ← upgraded
      5. Bollinger Band upper breakout            (+2)
      6. Near 52-week high (within 3%)            (+3)
      7. EMA20/50 golden cross (last 5 days)      (+3)
      8. Supertrend fresh bullish crossover       (+3)  ← NEW
         OR Supertrend already bullish            (+1)  ← NEW
      9. Price above EMA200 (macro bull filter)   (+1)  ← NEW (was unused)
    Minimum score to emit a signal: 5
    """
    if len(df) < 30:
        return None

    df    = add_indicators(df)
    last  = df.iloc[-1]
    prev  = df.iloc[-2]
    close = last["close"]

    # Basic filters
    if not (MIN_PRICE <= close <= MAX_PRICE):
        return None
    required = ["ema20", "ema50", "rsi", "vol_ratio"]
    if any(pd.isna(last.get(col)) for col in required):
        return None

    reasons = []
    score   = 0
    rsi     = last["rsi"]

    # 1. Volume breakout – upgraded: 20-day high + 2x volume = high conviction
    high_20d = last.get("high_20d")
    if high_20d and not pd.isna(high_20d) and close > high_20d and last["vol_ratio"] >= 2.0:
        score += 3
        reasons.append(f"20d price breakout + vol {last['vol_ratio']:.1f}x")
    elif last["vol_ratio"] >= VOLUME_SURGE_FACTOR:
        score += 1
        reasons.append(f"Volume surge {last['vol_ratio']:.1f}x avg")

    # 2. RSI momentum (not overbought)
    if RSI_BREAKOUT_MIN <= rsi <= RSI_OVERBOUGHT:
        score += 2
        reasons.append(f"RSI={rsi:.1f} momentum zone")

    # 3. EMA trend alignment
    if close > last["ema20"] > last["ema50"]:
        score += 2
        reasons.append("EMA20 > EMA50 bull alignment")

    # 4. MACD crossover – upgraded: bonus when crossover is below zero line
    macd_hist_now  = last.get("macd_hist", 0) or 0
    macd_hist_prev = prev.get("macd_hist", 1) or 1
    macd_val       = last.get("macd", 0)      or 0
    if macd_hist_now > 0 and macd_hist_prev <= 0:
        if macd_val < 0:   # crossover while MACD still negative = stronger setup
            score += 4
            reasons.append("MACD zero-line crossover (high-potential setup)")
        else:
            score += 2
            reasons.append("MACD bullish crossover")

    # 5. Bollinger Band upper breakout
    bb_upper = last.get("bb_upper")
    if bb_upper and not pd.isna(bb_upper) and close >= bb_upper:
        score += 2
        reasons.append("BB upper band breakout")

    # 6. Near 52-week high (within 3%)
    high_52w = last.get("high_52w")
    if high_52w and not pd.isna(high_52w) and close >= 0.97 * high_52w:
        score += 3
        reasons.append(f"Near 52W high ₹{high_52w:.2f}")

    # 7. EMA20/50 golden cross in last 5 days
    recent     = df.tail(5)
    crossovers = (
        (recent["ema20"] > recent["ema50"]) &
        (recent["ema20"].shift(1) <= recent["ema50"].shift(1))
    )
    if crossovers.any():
        score += 3
        reasons.append("EMA20/50 golden cross")

    # 8. Supertrend fresh bullish crossover (NEW)
    s_dir_now  = last.get("supertrend_dir")
    s_dir_prev = prev.get("supertrend_dir")
    if s_dir_now is not None and not pd.isna(s_dir_now):
        if s_dir_now == 1 and s_dir_prev == -1:   # fresh flip to bullish
            score += 3
            reasons.append("Supertrend bullish crossover")
        elif s_dir_now == 1:                        # already bullish confirmation
            score += 1
            reasons.append("Supertrend bullish")

    # 9. Price above EMA200 — macro bull filter (NEW, was computed but unused)
    ema200 = last.get("ema200")
    if ema200 is not None and not pd.isna(ema200) and close > ema200:
        score += 1
        reasons.append("Above EMA200 (macro uptrend)")

    if score < 7:
        return None

    stage     = get_stage(df)
    atr14     = last.get("atr14")
    swing_low = find_swing_low(df)
    high_52w  = last.get("high_52w")

    return {
        "signal_type": "BREAKOUT",
        "symbol":      df["symbol"].iloc[0] if "symbol" in df.columns else "?",
        "close":       round(close, 2),
        "rsi":         round(rsi, 1),
        "vol_ratio":   round(last["vol_ratio"], 2),
        "score":       score,
        "stage":       stage,
        "reasons":     "; ".join(reasons),
        "ema20":       round(last["ema20"], 2),
        "ema50":       round(last["ema50"], 2),
        "atr14":       round(float(atr14), 2) if atr14 is not None and not pd.isna(atr14) else None,
        "swing_low":   round(swing_low, 2)    if swing_low is not None else None,
        "high_52w":    round(float(high_52w), 2) if high_52w is not None and not pd.isna(high_52w) else None,
    }


# ── MA Pullback Scanner ───────────────────────────────────────────────────────

def is_ma_pullback(df: pd.DataFrame) -> dict | None:
    """
    MA Pullback (buy-the-dip) signal — fundamentally different from a breakout.
    All four conditions must be TRUE (no scoring — pass/fail):

      1. EMA50 > EMA200           → macro uptrend confirmed
      2. Current Low  <= EMA50    → price dipped down to the 50 EMA (the dip)
      3. Current Close > EMA50    → buyers defended the level (reversal candle)
      4. RSI (14) < 45            → short-term oversold / beaten-down

    Stop loss: 1.5×ATR below close, tightened by swing low if available.
    """
    if len(df) < 60:       # need enough history for EMA200 to be meaningful
        return None

    df   = add_indicators(df)
    last = df.iloc[-1]

    close  = float(last["close"])
    low    = float(last["low"])
    ema50  = last.get("ema50")
    ema200 = last.get("ema200")
    rsi    = last.get("rsi")

    # All four conditions must be valid numbers
    for v in [close, ema50, ema200, rsi]:
        if v is None or pd.isna(v):
            return None

    ema50  = float(ema50)
    ema200 = float(ema200)
    rsi    = float(rsi)

    if not (MIN_PRICE <= close <= MAX_PRICE):  return None
    if ema50 <= ema200:                         return None   # macro downtrend — skip
    if not (low <= ema50 <= close):             return None   # must dip to & close above EMA50
    if rsi >= 45:                               return None   # not oversold enough

    atr14     = last.get("atr14")
    atr14     = float(atr14) if atr14 is not None and not pd.isna(atr14) else None
    swing_low = find_swing_low(df)
    sl        = _sl_from_atr_and_swing(close, atr14, swing_low)
    high_52w  = last.get("high_52w")

    vol_ratio = last.get("vol_ratio")
    vol_ratio = float(vol_ratio) if vol_ratio is not None and not pd.isna(vol_ratio) else 0.0

    return {
        "signal_type": "PULLBACK",
        "symbol":      df["symbol"].iloc[0] if "symbol" in df.columns else "?",
        "close":       round(close, 2),
        "rsi":         round(rsi, 1),
        "vol_ratio":   round(vol_ratio, 2),
        "score":       6,      # binary pass — all conditions met
        "stage":       "Stage2",
        "reasons":     (f"50 EMA pullback | RSI={rsi:.0f} oversold | "
                        f"EMA50 defended | macro EMA50>{ema200:.0f}"),
        "ema20":       round(float(last["ema20"]), 2) if not pd.isna(last.get("ema20")) else None,
        "ema50":       round(ema50, 2),
        "atr14":       round(atr14, 2) if atr14 else None,
        "swing_low":   round(swing_low, 2) if swing_low else None,
        "high_52w":    round(float(high_52w), 2) if high_52w is not None and not pd.isna(high_52w) else None,
    }
