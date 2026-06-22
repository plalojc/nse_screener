
# ============================================================
# analysis/breakout_scanner.py - Breakout + Pullback signal detection
# ============================================================
import pandas as pd
from analysis.technical import add_indicators, get_stage
from config import (VOLUME_SURGE_FACTOR, RSI_BREAKOUT_MIN,
                    RSI_OVERBOUGHT, MIN_PRICE, MAX_PRICE, ATR_SL_MULTIPLIER,
                    MIN_TURNOVER_CR, MIN_BREAKOUT_SCORE,
                    MAX_EMA20_EXTENSION_PCT, MAX_DAY_RANGE_ATR,
                    MIN_CLOSE_RANGE_POS, MIN_STAGE1_SCORE,
                    STAGE1_NEAR_BREAKOUT_PCT, STAGE1_RSI_MIN,
                    STAGE1_RSI_MAX, MIN_WATCHLIST_SCORE,
                    MIN_WATCHLIST_TURNOVER_CR, WATCHLIST_NEAR_HIGH_PCT,
                    MAX_BREAKOUT_ABOVE_TRIGGER_PCT)


INDICATOR_COLUMNS = {
    "ema20", "ema50", "ema200", "rsi", "vol_ratio", "atr14",
    "high_20d", "high_55d", "high_52w", "turnover_cr",
    "close_range_pos", "day_range_atr", "ema20_extension_pct",
    "ema50_extension_pct", "macd_hist", "supertrend_dir",
}


def _ensure_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Reuse enriched OHLCV frames when the orchestrator already added indicators."""
    if INDICATOR_COLUMNS.issubset(df.columns):
        return df
    return add_indicators(df)


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


def passes_breakout_prefilter(df: pd.DataFrame) -> bool:
    """
    Cheap raw-candle gate before expensive TA indicators are calculated.

    This only checks conditions that must already be true for is_breakout():
    enough history, price/liquidity, strong close, and a fresh 20d/55d break.
    """
    if len(df) < 60:
        return False

    last = df.iloc[-1]
    close = pd.to_numeric(last.get("close"), errors="coerce")
    high = pd.to_numeric(last.get("high"), errors="coerce")
    low = pd.to_numeric(last.get("low"), errors="coerce")
    volume = pd.to_numeric(last.get("volume"), errors="coerce")
    if any(pd.isna(v) for v in (close, high, low, volume)):
        return False
    if not (MIN_PRICE <= close <= MAX_PRICE):
        return False

    turnover_cr = (close * volume) / 10_000_000
    if turnover_cr < MIN_TURNOVER_CR:
        return False

    day_range = high - low
    if day_range <= 0:
        return False
    close_range_pos = (close - low) / day_range
    if close_range_pos < MIN_CLOSE_RANGE_POS:
        return False

    prior_high = pd.to_numeric(df["high"].shift(1), errors="coerce")
    high_20d = prior_high.rolling(20).max().iloc[-1]
    high_55d = prior_high.rolling(55).max().iloc[-1]
    return (
        (not pd.isna(high_55d) and close > high_55d)
        or (not pd.isna(high_20d) and close > high_20d)
    )


def passes_stage1_prefilter(df: pd.DataFrame) -> bool:
    """
    Cheap gate for Stage1 watchlist candidates.

    A Stage1 candidate is not a breakout yet. It should be liquid enough,
    close strongly, and sit close to a 20d/55d trigger so Grok reviews names
    that may be preparing for a move rather than every quiet stock.
    """
    if len(df) < 60:
        return False

    last = df.iloc[-1]
    close = pd.to_numeric(last.get("close"), errors="coerce")
    high = pd.to_numeric(last.get("high"), errors="coerce")
    low = pd.to_numeric(last.get("low"), errors="coerce")
    volume = pd.to_numeric(last.get("volume"), errors="coerce")
    if any(pd.isna(v) for v in (close, high, low, volume)):
        return False
    if not (MIN_PRICE <= close <= MAX_PRICE):
        return False

    turnover_cr = (close * volume) / 10_000_000
    if turnover_cr < MIN_TURNOVER_CR:
        return False

    day_range = high - low
    if day_range <= 0:
        return False
    close_range_pos = (close - low) / day_range
    if close_range_pos < MIN_CLOSE_RANGE_POS:
        return False

    prior_high = pd.to_numeric(df["high"].shift(1), errors="coerce")
    high_20d = prior_high.rolling(20).max().iloc[-1]
    high_55d = prior_high.rolling(55).max().iloc[-1]
    usable_highs = [h for h in (high_20d, high_55d) if not pd.isna(h) and h > 0]
    if not usable_highs:
        return False
    nearest_high = min(usable_highs)
    distance_pct = (nearest_high - close) / nearest_high * 100
    return 0 <= distance_pct <= STAGE1_NEAR_BREAKOUT_PCT


def passes_pullback_prefilter(df: pd.DataFrame) -> bool:
    """
    Cheap gate for EMA50 pullback candidates.

    The full pullback scanner needs all indicators, including ATR. This gate
    calculates only EMA50/EMA200 and RSI so quiet symbols avoid the heavier
    full-indicator path.
    """
    if len(df) < 200:
        return False

    close_series = pd.to_numeric(df["close"], errors="coerce")
    low_series = pd.to_numeric(df["low"], errors="coerce")
    high_series = pd.to_numeric(df["high"], errors="coerce")
    volume_series = pd.to_numeric(df["volume"], errors="coerce")
    close = close_series.iloc[-1]
    low = low_series.iloc[-1]
    high = high_series.iloc[-1]
    volume = volume_series.iloc[-1]
    if any(pd.isna(v) for v in (close, low, high, volume)):
        return False
    if not (MIN_PRICE <= close <= MAX_PRICE):
        return False

    turnover_cr = (close * volume) / 10_000_000
    if turnover_cr < MIN_TURNOVER_CR:
        return False

    ema50 = close_series.ewm(span=50, adjust=False, min_periods=50).mean().iloc[-1]
    ema200 = close_series.ewm(span=200, adjust=False, min_periods=200).mean().iloc[-1]
    if pd.isna(ema50) or pd.isna(ema200) or ema50 <= ema200:
        return False
    if not (low <= ema50 <= close):
        return False

    delta = close_series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    rsi = (100 - (100 / (1 + rs))).iloc[-1]
    return not pd.isna(rsi) and rsi < 48


def passes_watchlist_prefilter(df: pd.DataFrame) -> bool:
    """
    Cheap gate for lower-priority AI-fill candidates.

    It checks only raw OHLCV, liquidity, strong close, and proximity to recent
    highs. Full indicators are calculated only after this passes.
    """
    if len(df) < 60:
        return False

    last = df.iloc[-1]
    close = pd.to_numeric(last.get("close"), errors="coerce")
    high = pd.to_numeric(last.get("high"), errors="coerce")
    low = pd.to_numeric(last.get("low"), errors="coerce")
    volume = pd.to_numeric(last.get("volume"), errors="coerce")
    if any(pd.isna(v) for v in (close, high, low, volume)):
        return False
    if not (MIN_PRICE <= close <= MAX_PRICE):
        return False

    turnover_cr = (close * volume) / 10_000_000
    if turnover_cr < MIN_WATCHLIST_TURNOVER_CR:
        return False

    day_range = high - low
    if day_range <= 0:
        return False
    close_range_pos = (close - low) / day_range
    if close_range_pos < 0.45:
        return False

    prior_high = pd.to_numeric(df["high"].shift(1), errors="coerce")
    high_20d = prior_high.rolling(20).max().iloc[-1]
    high_55d = prior_high.rolling(55).max().iloc[-1]
    usable_highs = [h for h in (high_20d, high_55d) if not pd.isna(h) and h > 0]
    if not usable_highs:
        return False
    trigger_high = min(usable_highs)
    trigger_distance_pct = (trigger_high - close) / trigger_high * 100
    return trigger_distance_pct <= WATCHLIST_NEAR_HIGH_PCT


# == Breakout Scanner ==========================================================

def is_breakout(df: pd.DataFrame) -> dict | None:
    """
    2-4 week swing breakout signal.
    The goal is not to catch every one-day spike. Prefer fresh breakouts from a
    Stage2 trend with enough liquidity, strong close, and room for 2R follow-through.
    """
    if len(df) < 60:
        return None

    df    = _ensure_indicators(df)
    last  = df.iloc[-1]
    prev  = df.iloc[-2]
    close = last["close"]
    stage = get_stage(df)

    # Basic filters
    if not (MIN_PRICE <= close <= MAX_PRICE):
        return None
    required = [
        "ema20", "ema50", "rsi", "vol_ratio", "atr14", "high_20d",
        "turnover_cr", "close_range_pos", "day_range_atr",
        "ema20_extension_pct",
    ]
    if any(pd.isna(last.get(col)) for col in required):
        return None
    if stage == "Stage3":
        return None

    reasons = []
    score   = 0
    rsi     = last["rsi"]
    vol_ratio = float(last["vol_ratio"])
    atr14 = float(last["atr14"])
    turnover_cr = float(last["turnover_cr"])
    close_range_pos = float(last["close_range_pos"])
    day_range_atr = float(last["day_range_atr"])
    ema20_extension_pct = float(last["ema20_extension_pct"])
    ema50_extension_pct = float(last.get("ema50_extension_pct") or 0)

    if turnover_cr < MIN_TURNOVER_CR:
        return None
    if close_range_pos < MIN_CLOSE_RANGE_POS:
        return None
    if day_range_atr > MAX_DAY_RANGE_ATR:
        return None
    if ema20_extension_pct > MAX_EMA20_EXTENSION_PCT:
        return None

    # 1. Fresh price breakout. 55-day highs tend to work better for 2-4 week swings.
    high_20d = last.get("high_20d")
    high_55d = last.get("high_55d")
    has_price_breakout = False
    breakout_lookback = None
    if high_55d and not pd.isna(high_55d) and close > high_55d:
        has_price_breakout = True
        breakout_lookback = 55
        score += 5
        reasons.append("Fresh 55d breakout")
    elif high_20d and not pd.isna(high_20d) and close > high_20d:
        has_price_breakout = True
        breakout_lookback = 20
        score += 3
        reasons.append("Fresh 20d breakout")
    if not has_price_breakout:
        return None

    # 1b. Freshness cap. In early/both/best modes reject breakouts that have
    # already run far past their trigger high (avoids buying extended / ATH spikes).
    trigger_high = high_55d if breakout_lookback == 55 else high_20d
    if trigger_high and not pd.isna(trigger_high) and trigger_high > 0:
        above_trigger_pct = (close - trigger_high) / trigger_high * 100
        if above_trigger_pct > MAX_BREAKOUT_ABOVE_TRIGGER_PCT:
            return None

    # 2. Volume expansion. Penalize likely exhaustion spikes.
    if 1.8 <= vol_ratio <= 5.0:
        score += 3
        reasons.append(f"Healthy volume expansion {vol_ratio:.1f}x")
    elif VOLUME_SURGE_FACTOR <= vol_ratio < 1.8:
        score += 1
        reasons.append(f"Volume surge {vol_ratio:.1f}x avg")
    elif vol_ratio > 5.0:
        score += 1
        reasons.append(f"Very high volume {vol_ratio:.1f}x; watch exhaustion")

    # 3. RSI momentum (not overbought)
    if RSI_BREAKOUT_MIN <= rsi <= min(RSI_OVERBOUGHT, 75):
        score += 3
        reasons.append(f"RSI={rsi:.1f} clean momentum")
    elif 75 < rsi <= RSI_OVERBOUGHT:
        score += 1
        reasons.append(f"RSI={rsi:.1f} extended but valid")

    # 4. Trend alignment
    if close > last["ema20"] > last["ema50"]:
        score += 2
        reasons.append("EMA20 > EMA50 bull alignment")
    if stage == "Stage2":
        score += 2
        reasons.append("Stage2 trend")

    ema200 = last.get("ema200")
    if ema200 is not None and not pd.isna(ema200) and close > ema200:
        score += 2
        reasons.append("Above EMA200 macro trend")

    # 5. Entry quality for 2-4 week holding period.
    if close_range_pos >= 0.7:
        score += 2
        reasons.append("Strong close near high")
    if ema20_extension_pct <= 6:
        score += 2
        reasons.append(f"Not extended from EMA20 ({ema20_extension_pct:.1f}%)")
    elif ema20_extension_pct <= MAX_EMA20_EXTENSION_PCT:
        score += 1
        reasons.append(f"Acceptable EMA20 extension ({ema20_extension_pct:.1f}%)")

    # 6. MACD crossover
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

    # 7. Bollinger Band upper breakout
    bb_upper = last.get("bb_upper")
    if bb_upper and not pd.isna(bb_upper) and close >= bb_upper:
        score += 1
        reasons.append("BB upper band breakout")

    # 8. Near 52-week high (within 5%)
    high_52w = last.get("high_52w")
    if high_52w and not pd.isna(high_52w) and close >= 0.95 * high_52w:
        score += 2
        reasons.append(f"Near 52W high Rs.{high_52w:.2f}")

    # 9. EMA20/50 golden cross in last 10 days
    recent     = df.tail(10)
    crossovers = (
        (recent["ema20"] > recent["ema50"]) &
        (recent["ema20"].shift(1) <= recent["ema50"].shift(1))
    )
    if crossovers.any():
        score += 2
        reasons.append("EMA20/50 golden cross")

    # 10. Supertrend confirmation
    s_dir_now  = last.get("supertrend_dir")
    s_dir_prev = prev.get("supertrend_dir")
    if s_dir_now is not None and not pd.isna(s_dir_now):
        if s_dir_now == 1 and s_dir_prev == -1:   # fresh flip to bullish
            score += 2
            reasons.append("Supertrend bullish crossover")
        elif s_dir_now == 1:                        # already bullish confirmation
            score += 1
            reasons.append("Supertrend bullish")

    swing_low = find_swing_low(df)
    sl = _sl_from_atr_and_swing(close, atr14, swing_low)
    entry_risk_pct = (close - sl) / close * 100 if close > sl else 99
    if entry_risk_pct <= 6:
        score += 2
        reasons.append(f"Manageable risk {entry_risk_pct:.1f}%")
    elif entry_risk_pct <= 8:
        score += 1
        reasons.append(f"Wide but acceptable risk {entry_risk_pct:.1f}%")
    else:
        return None

    if score < MIN_BREAKOUT_SCORE:
        return None

    return {
        "signal_type": "BREAKOUT",
        "symbol":      df["symbol"].iloc[0] if "symbol" in df.columns else "?",
        "close":       round(close, 2),
        "rsi":         round(rsi, 1),
        "vol_ratio":   round(vol_ratio, 2),
        "score":       score,
        "swing_score": score,
        "stage":       stage,
        "reasons":     "; ".join(reasons),
        "ema20":          round(last["ema20"], 2),
        "ema50":          round(last["ema50"], 2),
        "ema200":         round(float(ema200), 2) if ema200 is not None and not pd.isna(ema200) else None,
        "macd_hist":      round(float(last.get("macd_hist")), 4)
                          if last.get("macd_hist") is not None and not pd.isna(last.get("macd_hist")) else None,
        "supertrend_dir": int(last.get("supertrend_dir"))
                          if last.get("supertrend_dir") is not None and not pd.isna(last.get("supertrend_dir")) else None,
        "atr14":          round(float(atr14), 2) if atr14 is not None and not pd.isna(atr14) else None,
        "swing_low":      round(swing_low, 2)    if swing_low is not None else None,
        "high_52w":       round(float(high_52w), 2) if high_52w is not None and not pd.isna(high_52w) else None,
        "turnover_cr":    round(float(turnover_cr), 2),
        "entry_risk_pct": round(float(entry_risk_pct), 2),
        "ema20_extension_pct": round(float(ema20_extension_pct), 2),
        "ema50_extension_pct": round(float(ema50_extension_pct), 2),
        "close_range_pos": round(float(close_range_pos), 2),
        "day_range_atr": round(float(day_range_atr), 2),
        "breakout_lookback": breakout_lookback,
    }


def is_stage1_watchlist(df: pd.DataFrame) -> dict | None:
    """
    Stage1 pre-breakout watchlist signal.

    This is intentionally separate from BREAKOUT. It lets the LLM review
    accumulation/near-breakout stocks without diluting the stricter breakout
    signal rules.
    """
    if len(df) < 60:
        return None

    df = _ensure_indicators(df)
    last = df.iloc[-1]
    close = last["close"]
    stage = get_stage(df)

    if stage != "Stage1":
        return None
    if not (MIN_PRICE <= close <= MAX_PRICE):
        return None

    required = [
        "ema20", "ema50", "rsi", "vol_ratio", "atr14", "high_20d",
        "high_55d", "high_52w", "turnover_cr", "close_range_pos",
        "day_range_atr", "bb_width",
    ]
    if any(pd.isna(last.get(col)) for col in required):
        return None

    rsi = float(last["rsi"])
    vol_ratio = float(last["vol_ratio"])
    atr14 = float(last["atr14"])
    turnover_cr = float(last["turnover_cr"])
    close_range_pos = float(last["close_range_pos"])
    day_range_atr = float(last["day_range_atr"])
    bb_width = float(last.get("bb_width") or 0)
    ema20 = float(last["ema20"])
    ema50 = float(last["ema50"])
    ema200 = last.get("ema200")
    high_20d = float(last["high_20d"])
    high_55d = float(last["high_55d"])
    high_52w = last.get("high_52w")

    if turnover_cr < MIN_TURNOVER_CR:
        return None
    if close_range_pos < MIN_CLOSE_RANGE_POS:
        return None
    if day_range_atr > MAX_DAY_RANGE_ATR:
        return None
    if not (STAGE1_RSI_MIN <= rsi <= STAGE1_RSI_MAX):
        return None
    if close > high_20d or close > high_55d:
        return None

    trigger_high = min(high_20d, high_55d)
    near_breakout_pct = (trigger_high - close) / trigger_high * 100
    if near_breakout_pct < 0 or near_breakout_pct > STAGE1_NEAR_BREAKOUT_PCT:
        return None

    reasons = []
    score = 0

    if near_breakout_pct <= 2:
        score += 3
        reasons.append(f"Within {near_breakout_pct:.1f}% of breakout trigger")
    else:
        score += 2
        reasons.append(f"Near breakout trigger ({near_breakout_pct:.1f}% away)")

    if STAGE1_RSI_MIN <= rsi <= STAGE1_RSI_MAX:
        score += 2
        reasons.append(f"RSI={rsi:.1f} constructive for Stage1")
    if vol_ratio >= 1.5:
        score += 2
        reasons.append(f"Accumulation volume {vol_ratio:.1f}x")
    elif vol_ratio >= 1.1:
        score += 1
        reasons.append(f"Volume improving {vol_ratio:.1f}x")

    ema_spread_pct = abs(ema20 - ema50) / ema50 * 100 if ema50 else 99
    if ema_spread_pct <= 3:
        score += 2
        reasons.append("EMA20/50 compression")
    elif ema_spread_pct <= 6:
        score += 1
        reasons.append("Moderate EMA20/50 compression")

    if bb_width <= 8:
        score += 2
        reasons.append("Tight Bollinger compression")
    elif bb_width <= 12:
        score += 1
        reasons.append("Moderate Bollinger compression")

    if ema200 is not None and not pd.isna(ema200) and close > ema200:
        score += 2
        reasons.append("Above EMA200 base")
    if close_range_pos >= 0.7:
        score += 1
        reasons.append("Strong close inside base")

    swing_low = find_swing_low(df)
    sl = _sl_from_atr_and_swing(close, atr14, swing_low)
    entry_risk_pct = (close - sl) / close * 100 if close > sl else 99
    if entry_risk_pct <= 8:
        score += 1
        reasons.append(f"Watchlist risk {entry_risk_pct:.1f}%")

    if score < MIN_STAGE1_SCORE:
        return None

    return {
        "signal_type": "STAGE1",
        "symbol": df["symbol"].iloc[0] if "symbol" in df.columns else "?",
        "close": round(float(close), 2),
        "rsi": round(rsi, 1),
        "vol_ratio": round(vol_ratio, 2),
        "score": score,
        "swing_score": score,
        "stage": stage,
        "reasons": "; ".join(reasons),
        "ema20": round(ema20, 2),
        "ema50": round(ema50, 2),
        "ema200": round(float(ema200), 2) if ema200 is not None and not pd.isna(ema200) else None,
        "macd_hist": round(float(last.get("macd_hist")), 4)
                     if last.get("macd_hist") is not None and not pd.isna(last.get("macd_hist")) else None,
        "supertrend_dir": int(last.get("supertrend_dir"))
                          if last.get("supertrend_dir") is not None and not pd.isna(last.get("supertrend_dir")) else None,
        "atr14": round(atr14, 2),
        "swing_low": round(swing_low, 2) if swing_low is not None else None,
        "high_52w": round(float(high_52w), 2) if high_52w is not None and not pd.isna(high_52w) else None,
        "turnover_cr": round(turnover_cr, 2),
        "entry_risk_pct": round(entry_risk_pct, 2),
        "ema20_extension_pct": round((close - ema20) / ema20 * 100, 2) if ema20 else None,
        "ema50_extension_pct": round((close - ema50) / ema50 * 100, 2) if ema50 else None,
        "close_range_pos": round(close_range_pos, 2),
        "day_range_atr": round(day_range_atr, 2),
        "breakout_lookback": "near",
    }


def is_llm_watchlist_candidate(df: pd.DataFrame) -> dict | None:
    """
    Lower-priority candidate used only to fill the LLM review queue.

    These are not trade signals. They are ranked "interesting enough" stocks
    that Grok/Gemini can review after stronger BREAKOUT/STAGE1/PULLBACK setups.
    """
    if len(df) < 60:
        return None

    df = _ensure_indicators(df)
    last = df.iloc[-1]
    close = last["close"]
    stage = get_stage(df)

    if stage == "Stage3":
        return None
    if not (MIN_PRICE <= close <= MAX_PRICE):
        return None

    required = [
        "ema20", "ema50", "rsi", "vol_ratio", "atr14", "high_20d",
        "high_55d", "high_52w", "turnover_cr", "close_range_pos",
        "day_range_atr", "ema20_extension_pct",
    ]
    if any(pd.isna(last.get(col)) for col in required):
        return None

    rsi = float(last["rsi"])
    vol_ratio = float(last["vol_ratio"])
    atr14 = float(last["atr14"])
    turnover_cr = float(last["turnover_cr"])
    close_range_pos = float(last["close_range_pos"])
    day_range_atr = float(last["day_range_atr"])
    ema20 = float(last["ema20"])
    ema50 = float(last["ema50"])
    ema200 = last.get("ema200")
    high_20d = float(last["high_20d"])
    high_55d = float(last["high_55d"])
    high_52w = last.get("high_52w")
    ema20_extension_pct = float(last["ema20_extension_pct"])

    if turnover_cr < MIN_WATCHLIST_TURNOVER_CR:
        return None
    if day_range_atr > MAX_DAY_RANGE_ATR * 1.25:
        return None
    if close_range_pos < 0.45:
        return None
    if ema20_extension_pct > MAX_EMA20_EXTENSION_PCT * 1.25:
        return None

    usable_highs = [h for h in (high_20d, high_55d) if h > 0]
    if not usable_highs:
        return None
    trigger_high = min(usable_highs)
    trigger_distance_pct = (trigger_high - close) / trigger_high * 100
    if trigger_distance_pct > WATCHLIST_NEAR_HIGH_PCT:
        return None

    reasons = []
    score = 0

    if stage == "Stage2":
        score += 3
        reasons.append("Stage2 watchlist trend")
    elif stage == "Stage1":
        score += 2
        reasons.append("Stage1 watchlist base")

    if close >= high_55d:
        score += 3
        reasons.append("At/above 55d trigger but missed strict filters")
    elif close >= high_20d:
        score += 2
        reasons.append("At/above 20d trigger but missed strict filters")
    elif trigger_distance_pct <= 5:
        score += 2
        reasons.append(f"Within {trigger_distance_pct:.1f}% of trigger")
    else:
        score += 1
        reasons.append(f"Near trigger ({trigger_distance_pct:.1f}% away)")

    if 50 <= rsi <= 70:
        score += 2
        reasons.append(f"Constructive RSI={rsi:.1f}")
    elif 45 <= rsi <= 75:
        score += 1
        reasons.append(f"Acceptable RSI={rsi:.1f}")

    if vol_ratio >= 1.5:
        score += 2
        reasons.append(f"Volume improving {vol_ratio:.1f}x")
    elif vol_ratio >= 1.1:
        score += 1
        reasons.append(f"Some volume support {vol_ratio:.1f}x")

    if close > ema20:
        score += 1
        reasons.append("Above EMA20")
    if close > ema50:
        score += 1
        reasons.append("Above EMA50")
    if ema200 is not None and not pd.isna(ema200) and close > ema200:
        score += 1
        reasons.append("Above EMA200")
    if high_52w is not None and not pd.isna(high_52w) and high_52w > 0:
        near_52w_pct = (high_52w - close) / high_52w * 100
        if near_52w_pct <= 15:
            score += 2
            reasons.append(f"Within {near_52w_pct:.1f}% of 52W high")
        elif near_52w_pct <= 30:
            score += 1
            reasons.append(f"Within {near_52w_pct:.1f}% of 52W high")

    swing_low = find_swing_low(df)
    sl = _sl_from_atr_and_swing(close, atr14, swing_low)
    entry_risk_pct = (close - sl) / close * 100 if close > sl else 99
    if entry_risk_pct <= 8:
        score += 1
        reasons.append(f"Risk {entry_risk_pct:.1f}%")

    if score < MIN_WATCHLIST_SCORE:
        return None

    return {
        "signal_type": "WATCHLIST",
        "symbol": df["symbol"].iloc[0] if "symbol" in df.columns else "?",
        "close": round(float(close), 2),
        "rsi": round(rsi, 1),
        "vol_ratio": round(vol_ratio, 2),
        "score": score,
        "swing_score": score,
        "stage": stage,
        "reasons": "; ".join(reasons),
        "ema20": round(ema20, 2),
        "ema50": round(ema50, 2),
        "ema200": round(float(ema200), 2) if ema200 is not None and not pd.isna(ema200) else None,
        "macd_hist": round(float(last.get("macd_hist")), 4)
                     if last.get("macd_hist") is not None and not pd.isna(last.get("macd_hist")) else None,
        "supertrend_dir": int(last.get("supertrend_dir"))
                          if last.get("supertrend_dir") is not None and not pd.isna(last.get("supertrend_dir")) else None,
        "atr14": round(atr14, 2),
        "swing_low": round(swing_low, 2) if swing_low is not None else None,
        "high_52w": round(float(high_52w), 2) if high_52w is not None and not pd.isna(high_52w) else None,
        "turnover_cr": round(turnover_cr, 2),
        "entry_risk_pct": round(entry_risk_pct, 2),
        "ema20_extension_pct": round(ema20_extension_pct, 2),
        "ema50_extension_pct": round((close - ema50) / ema50 * 100, 2) if ema50 else None,
        "close_range_pos": round(close_range_pos, 2),
        "day_range_atr": round(day_range_atr, 2),
        "breakout_lookback": "watch",
    }


# == MA Pullback Scanner =======================================================

def is_ma_pullback(df: pd.DataFrame) -> dict | None:
    """
    MA Pullback (buy-the-dip) signal - fundamentally different from a breakout.
    All four conditions must be TRUE (no scoring - pass/fail):

      1. EMA50 > EMA200           -> macro uptrend confirmed
      2. Current Low  <= EMA50    -> price dipped down to the 50 EMA (the dip)
      3. Current Close > EMA50    -> buyers defended the level (reversal candle)
      4. RSI (14) < 45            -> short-term oversold / beaten-down

    Stop loss: 1.5xATR below close, tightened by swing low if available.
    """
    if len(df) < 60:       # need enough history for EMA200 to be meaningful
        return None

    df   = _ensure_indicators(df)
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
    if ema50 <= ema200:                         return None   # macro downtrend - skip
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
        "score":       6,      # binary pass - all conditions met
        "stage":       "Stage2",
        "reasons":     (f"50 EMA pullback | RSI={rsi:.0f} oversold | "
                        f"EMA50 defended | macro EMA50>{ema200:.0f}"),
        "ema20":          round(float(last["ema20"]), 2) if not pd.isna(last.get("ema20")) else None,
        "ema50":          round(ema50, 2),
        "ema200":         round(ema200, 2),   # already validated non-null above (line 195)
        "macd_hist":      round(float(last.get("macd_hist")), 4)
                          if last.get("macd_hist") is not None and not pd.isna(last.get("macd_hist")) else None,
        "supertrend_dir": int(last.get("supertrend_dir"))
                          if last.get("supertrend_dir") is not None and not pd.isna(last.get("supertrend_dir")) else None,
        "atr14":          round(atr14, 2) if atr14 else None,
        "swing_low":      round(swing_low, 2) if swing_low else None,
        "high_52w":       round(float(high_52w), 2) if high_52w is not None and not pd.isna(high_52w) else None,
    }
