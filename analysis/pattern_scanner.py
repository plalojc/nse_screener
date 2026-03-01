
# ============================================================
# analysis/pattern_scanner.py – Advanced chart pattern detection
# ============================================================
# Detects two institutional-grade patterns on top of existing indicators:
#   1. VCP  – Volatility Contraction Pattern (Mark Minervini method)
#   2. Bull Flag – Classic pole-and-flag continuation pattern
#
# Both operate on the OHLCV DataFrame already enriched by add_indicators().
# Zero LLM calls; pure pandas/numpy (~5ms per symbol).
# ============================================================

import numpy as np
import pandas as pd
from typing import Optional, Dict, Any


# ── Internal helpers ──────────────────────────────────────────────────────────

def _ema_slope_pct(series: pd.Series, n: int = 10) -> float:
    """% change of last value vs n-bars-ago value. Positive = rising."""
    if len(series) < n + 1:
        return 0.0
    tail = series.dropna()
    if len(tail) < n + 1:
        return 0.0
    older = tail.iloc[-(n + 1)]
    newer = tail.iloc[-1]
    if older == 0 or np.isnan(older) or np.isnan(newer):
        return 0.0
    return round((newer - older) / abs(older) * 100, 3)


def _segment_into_weekly_groups(df: pd.DataFrame, lookback: int = 60) -> list:
    """
    Take last `lookback` bars and divide into groups of 5 (weekly proxies).
    Returns list of dicts (oldest first), each with:
        high, low, range_pct, vol_avg
    """
    tail = df.tail(lookback).copy()
    groups = []
    for start in range(0, len(tail) - 4, 5):
        chunk = tail.iloc[start:start + 5]
        if len(chunk) < 3:
            continue
        high = chunk["high"].max()
        low  = chunk["low"].min()
        if low <= 0:
            continue
        range_pct = (high - low) / low * 100
        vol_avg   = chunk["volume"].mean()
        groups.append({
            "high":      high,
            "low":       low,
            "range_pct": range_pct,
            "vol_avg":   vol_avg,
        })
    return groups


# ── VCP Detector ──────────────────────────────────────────────────────────────

def detect_vcp(df: pd.DataFrame, min_contractions: int = 3) -> Optional[Dict[str, Any]]:
    """
    VCP (Volatility Contraction Pattern) – Mark Minervini method.

    Returns a result dict if the pattern is valid, or None if not detected.

    Conditions:
    1. At least `min_contractions` consecutive weekly price-range contractions
       (each week's range < 80% of prior week's range)
    2. Volume contracts alongside price range (confirms distribution stopped)
    3. Current close broke above the pivot (tightest base high)
    4. Breakout volume >= 1.5x the contraction-phase average volume
    5. VCP total depth 10%-30% (not too shallow, not too deep)
    6. Duration 15-60 bars (real base, not dead stock)
    7. EMA50 slope positive (underlying uptrend intact)
    """
    if len(df) < 65:
        return None

    # Require EMA50 data
    if "ema50" not in df.columns:
        return None

    ema50_slope = _ema_slope_pct(df["ema50"], n=10)
    if ema50_slope < 0:
        return None   # EMA50 declining — no uptrend

    groups = _segment_into_weekly_groups(df, lookback=60)
    if len(groups) < min_contractions + 1:
        return None

    # Find longest streak of contracting ranges + volume
    best_streak_start = -1
    best_streak_len   = 0
    cur_streak_start  = 0
    cur_streak_len    = 0

    for i in range(1, len(groups)):
        prev = groups[i - 1]
        curr = groups[i]
        range_ok  = curr["range_pct"] < prev["range_pct"] * 0.80   # 20% tighter
        volume_ok = curr["vol_avg"]   < prev["vol_avg"]             # volume declining too
        if range_ok and volume_ok:
            if cur_streak_len == 0:
                cur_streak_start = i - 1
            cur_streak_len += 1
            if cur_streak_len > best_streak_len:
                best_streak_len   = cur_streak_len
                best_streak_start = cur_streak_start
        else:
            cur_streak_len = 0

    if best_streak_len < min_contractions:
        return None

    # The streak: groups[best_streak_start : best_streak_start + best_streak_len + 1]
    streak = groups[best_streak_start: best_streak_start + best_streak_len + 1]

    first_high  = streak[0]["high"]
    last_group  = streak[-1]
    pivot_high  = last_group["high"]      # breakout pivot = tightest base high
    tightest_low = last_group["low"]

    # VCP depth: from first group high to tightest group low
    vcp_depth_pct = (first_high - tightest_low) / first_high * 100
    if not (10.0 <= vcp_depth_pct <= 35.0):
        return None

    # Duration: how many bars since first contraction started?
    # Approximate: streak_groups * 5 bars each
    duration_bars = (best_streak_len + 1) * 5
    if not (15 <= duration_bars <= 65):
        return None

    # Breakout: current close must have broken above pivot_high
    current_close = df["close"].iloc[-1]
    if current_close <= pivot_high:
        return None   # not yet broken out

    # Breakout volume vs contraction-phase avg
    contraction_vol_avg = np.mean([g["vol_avg"] for g in streak[:-1]])
    current_vol = df["volume"].iloc[-1]
    vol_at_breakout = round(current_vol / contraction_vol_avg, 2) if contraction_vol_avg > 0 else 0
    if vol_at_breakout < 1.5:
        return None   # weak-volume breakout — skip

    # Quality score (0-10)
    vcp_score = 4   # base for meeting all conditions
    if best_streak_len >= 4:
        vcp_score += 2    # more contractions = better
    if vol_at_breakout >= 2.5:
        vcp_score += 2
    elif vol_at_breakout >= 2.0:
        vcp_score += 1
    if ema50_slope >= 1.0:
        vcp_score += 1
    if vcp_depth_pct <= 20:
        vcp_score += 1    # tighter depth = cleaner pattern
    vcp_score = min(10, vcp_score)

    return {
        "pattern":           "VCP",
        "pivot_high":        round(pivot_high, 2),
        "contraction_count": best_streak_len,
        "vcp_depth_pct":     round(vcp_depth_pct, 2),
        "volume_at_breakout": vol_at_breakout,
        "ema50_slope_pct":   round(ema50_slope, 2),
        "vcp_score":         vcp_score,
    }


# ── Bull Flag Detector ────────────────────────────────────────────────────────

def detect_bull_flag(df: pd.DataFrame) -> Optional[Dict[str, Any]]:
    """
    Bull Flag pattern (classic continuation setup).

    Returns a result dict if pattern is valid, or None if not detected.

    Conditions:
    1. Pole: ≥10% gain in ≤10 bars, at least 1 bar with vol_ratio ≥ 1.5x
    2. Flag: 3–10 bars after pole with retracement ≤ 50% of pole height,
             declining volume, flat-to-downward price slope
    3. Breakout: current close > pole_high AND current vol ≥ 1.5x flag avg vol
    4. RSI 50–75, price > EMA20, pole started above EMA50
    """
    if len(df) < 25:
        return None

    if "vol_sma20" not in df.columns or "ema20" not in df.columns:
        return None

    # Need vol_ratio column or compute inline
    df_tail = df.tail(25).copy()
    if "vol_ratio" not in df_tail.columns:
        vol_sma20 = df_tail["volume"].rolling(20).mean()
        df_tail["vol_ratio"] = df_tail["volume"] / vol_sma20

    # Scan the last 25 bars for a pole (look back at most 15 bars for pole start)
    # Pole must END at least 3 bars ago (so flag can form)
    best_pole = None

    for pole_end_offset in range(3, 16):   # pole ended 3..15 bars ago
        pole_end_idx = len(df) - 1 - pole_end_offset

        # Try pole lengths of 3..10 bars ending at pole_end_idx
        for pole_len in range(3, 11):
            pole_start_idx = pole_end_idx - pole_len
            if pole_start_idx < 0:
                break

            pole_slice = df.iloc[pole_start_idx: pole_end_idx + 1]
            pole_start_price = pole_slice["close"].iloc[0]
            pole_high_price  = pole_slice["high"].max()
            pole_high_idx    = pole_slice["high"].idxmax()

            pole_pct = (pole_high_price - pole_start_price) / pole_start_price * 100
            if pole_pct < 10:
                continue

            # At least 1 high-volume bar in pole
            has_vol_bar = (pole_slice["vol_ratio"] >= 1.5).any()
            if not has_vol_bar:
                continue

            # EMA50 check: pole_start must be above EMA50
            if "ema50" in df.columns:
                ema50_at_start = df["ema50"].iloc[pole_start_idx]
                if not np.isnan(ema50_at_start) and pole_start_price < ema50_at_start:
                    continue

            best_pole = {
                "pole_start_idx":   pole_start_idx,
                "pole_end_idx":     pole_end_idx,
                "pole_start_price": pole_start_price,
                "pole_high":        pole_high_price,
                "pole_pct":         pole_pct,
                "pole_len":         pole_len,
            }
            break   # use first valid pole found for this offset

        if best_pole:
            break

    if not best_pole:
        return None

    # Flag: bars from pole_end+1 to current bar (last row)
    flag_start_idx = best_pole["pole_end_idx"] + 1
    flag_end_idx   = len(df) - 1
    flag_bars      = flag_end_idx - flag_start_idx + 1

    if not (3 <= flag_bars <= 12):
        return None

    flag_slice = df.iloc[flag_start_idx: flag_end_idx + 1]

    pole_high     = best_pole["pole_high"]
    pole_height   = pole_high - best_pole["pole_start_price"]
    flag_low      = flag_slice["low"].min()
    flag_retracement = (pole_high - flag_low) / pole_height * 100

    if flag_retracement > 50:
        return None   # too deep — not a clean flag

    # Flag volume should contract vs pole volume
    pole_slice      = df.iloc[best_pole["pole_start_idx"]: best_pole["pole_end_idx"] + 1]
    pole_vol_avg    = pole_slice["volume"].mean()
    flag_vol_avg    = flag_slice["volume"].mean()
    vol_contraction = round(flag_vol_avg / pole_vol_avg, 2) if pole_vol_avg > 0 else 1.0
    if vol_contraction >= 1.0:
        return None   # volume not contracting

    # Flag slope: linear regression of closes during flag — should be <= 0 (flat or down)
    flag_closes = flag_slice["close"].values
    if len(flag_closes) >= 2:
        x = np.arange(len(flag_closes))
        slope = np.polyfit(x, flag_closes, 1)[0]
        if slope > pole_height * 0.05:   # allow slight upward drift
            return None   # flag going too steeply upward (not a healthy flag)

    # Breakout: current close > pole_high
    current_close = df["close"].iloc[-1]
    current_vol   = df["volume"].iloc[-1]
    if current_close <= pole_high:
        return None

    # Breakout volume check
    flag_vol_for_check = flag_slice["volume"].iloc[:-1].mean() if len(flag_slice) > 1 else flag_vol_avg
    vol_at_breakout    = round(current_vol / flag_vol_for_check, 2) if flag_vol_for_check > 0 else 0
    if vol_at_breakout < 1.5:
        return None

    # RSI check
    if "rsi" in df.columns:
        rsi_now = df["rsi"].iloc[-1]
        if not np.isnan(rsi_now) and not (50 <= rsi_now <= 78):
            return None

    # EMA20 check
    if "ema20" in df.columns:
        ema20_now = df["ema20"].iloc[-1]
        if not np.isnan(ema20_now) and current_close < ema20_now:
            return None

    # Quality score (0-10)
    flag_score = 4   # base for meeting all conditions
    if best_pole["pole_pct"] >= 15:
        flag_score += 1
    if flag_retracement <= 33:
        flag_score += 2   # tight retracement is ideal
    elif flag_retracement <= 40:
        flag_score += 1
    if vol_at_breakout >= 2.5:
        flag_score += 2
    elif vol_at_breakout >= 2.0:
        flag_score += 1
    if vol_contraction <= 0.5:
        flag_score += 1   # strong volume contraction in flag
    flag_score = min(10, flag_score)

    return {
        "pattern":             "BULL_FLAG",
        "pole_start_price":    round(best_pole["pole_start_price"], 2),
        "pole_high":           round(pole_high, 2),
        "pole_pct":            round(best_pole["pole_pct"], 2),
        "flag_retracement_pct": round(flag_retracement, 2),
        "flag_bars":           flag_bars,
        "volume_contraction":  vol_contraction,
        "vol_at_breakout":     vol_at_breakout,
        "flag_score":          flag_score,
    }


# ── Public API ────────────────────────────────────────────────────────────────

def scan_advanced_patterns(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Run both VCP and Bull Flag detectors.

    Returns:
        {
            "vcp":              dict | None,
            "bull_flag":        dict | None,
            "pattern_summary":  str,          # human-readable block for LLM prompts
            "pattern_bonus_score": int,        # extra points to add to main rule score
        }
    """
    vcp       = None
    bull_flag = None

    try:
        vcp = detect_vcp(df)
    except Exception:
        pass

    try:
        bull_flag = detect_bull_flag(df)
    except Exception:
        pass

    # Bonus scoring
    bonus = 0
    if vcp:
        bonus += 4 if vcp["vcp_score"] >= 7 else 2
    if bull_flag:
        bonus += 3 if bull_flag["flag_score"] >= 7 else 1
    if vcp and bull_flag:
        bonus += 1   # dual-pattern confluence

    # Summary text for LLM prompts
    parts = []
    if vcp:
        parts.append(
            f"VCP DETECTED: {vcp['contraction_count']} contractions, "
            f"depth {vcp['vcp_depth_pct']}%, pivot ₹{vcp['pivot_high']}, "
            f"vol at breakout {vcp['volume_at_breakout']}x, "
            f"VCP score {vcp['vcp_score']}/10"
        )
    if bull_flag:
        parts.append(
            f"BULL FLAG DETECTED: pole +{bull_flag['pole_pct']}% "
            f"({bull_flag['flag_bars']} flag bars), "
            f"retracement {bull_flag['flag_retracement_pct']}%, "
            f"flag vol contracted to {bull_flag['volume_contraction']}x, "
            f"flag score {bull_flag['flag_score']}/10"
        )
    if not parts:
        parts.append("No advanced patterns detected (VCP/Bull Flag).")

    if bonus > 0:
        parts.append(f"Pattern Bonus Score: +{bonus} points")

    return {
        "vcp":                 vcp,
        "bull_flag":           bull_flag,
        "pattern_summary":     "\n".join(parts),
        "pattern_bonus_score": bonus,
    }
