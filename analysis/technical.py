
# ============================================================
# analysis/technical.py - Indicator computation (pandas-ta)
# ============================================================
import numpy as np
import pandas as pd
import pandas_ta as ta


def _safe(result, index):
    """
    pandas_ta functions return None when the series is too short.
    Convert None to a NaN Series so downstream comparisons stay safe.
    """
    if result is None:
        return pd.Series(np.nan, index=index)
    return result


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add all TA indicators needed for breakout detection."""
    required = {
        "ema20", "ema50", "ema200", "rsi", "macd", "macd_hist",
        "bb_upper", "bb_width", "vol_sma20", "vol_ratio", "turnover_cr",
        "turnover_sma20_cr", "atr14", "high_20d", "high_55d",
        "close_range_pos", "day_range_atr", "ema20_extension_pct",
        "ema50_extension_pct", "high_52w", "low_52w", "supertrend_dir",
    }
    if required.issubset(df.columns):
        return df

    df = df.copy()
    df["close"] = pd.to_numeric(df["close"])
    df["volume"] = pd.to_numeric(df["volume"])
    df["high"]   = pd.to_numeric(df["high"])
    df["low"]    = pd.to_numeric(df["low"])

    # Trend - _safe() turns None into NaN Series when data is too short
    df["ema20"]  = _safe(ta.ema(df["close"], length=20),  df.index)
    df["ema50"]  = _safe(ta.ema(df["close"], length=50),  df.index)
    df["ema200"] = _safe(ta.ema(df["close"], length=200), df.index)

    # Momentum
    df["rsi"]    = _safe(ta.rsi(df["close"], length=14),  df.index)

    # MACD - resolve column names dynamically (pandas_ta name format can vary)
    macd = ta.macd(df["close"], fast=12, slow=26, signal=9)
    if macd is not None and not macd.empty:
        _cols = macd.columns.tolist()
        _macd   = next((c for c in _cols if c.startswith("MACD_")
                        and not c.startswith("MACDs_")
                        and not c.startswith("MACDh_")), None)
        _signal = next((c for c in _cols if c.startswith("MACDs_")), None)
        _hist   = next((c for c in _cols if c.startswith("MACDh_")), None)
        if _macd:   df["macd"]        = macd[_macd]
        if _signal: df["macd_signal"] = macd[_signal]
        if _hist:   df["macd_hist"]   = macd[_hist]

    # Bollinger Bands - resolve column names dynamically
    bb = ta.bbands(df["close"], length=20, std=2)
    if bb is not None and not bb.empty:
        _cols = bb.columns.tolist()
        _upper = next((c for c in _cols if c.startswith("BBU_")), None)
        _lower = next((c for c in _cols if c.startswith("BBL_")), None)
        _width = next((c for c in _cols if c.startswith("BBB_")), None)
        if _upper: df["bb_upper"] = bb[_upper]
        if _lower: df["bb_lower"] = bb[_lower]
        if _width: df["bb_width"] = bb[_width]

    # Volume SMA
    df["vol_sma20"]     = df["volume"].rolling(20).mean()
    df["vol_ratio"]     = df["volume"] / df["vol_sma20"]
    df["turnover_cr"] = (df["close"] * df["volume"]) / 10_000_000
    df["turnover_sma20_cr"] = df["turnover_cr"].rolling(20).mean()

    # ATR (volatility)
    df["atr14"] = _safe(ta.atr(df["high"], df["low"], df["close"], length=14), df.index)

    # Prior rolling highs. Use shift(1) so today's candle can actually break out.
    prior_high = df["high"].shift(1)
    df["high_20d"] = prior_high.rolling(20).max()
    df["high_55d"] = prior_high.rolling(55).max()

    day_range = (df["high"] - df["low"]).replace(0, np.nan)
    df["close_range_pos"] = (df["close"] - df["low"]) / day_range
    df["day_range_atr"] = (df["high"] - df["low"]) / df["atr14"]
    df["ema20_extension_pct"] = (df["close"] - df["ema20"]) / df["ema20"] * 100
    df["ema50_extension_pct"] = (df["close"] - df["ema50"]) / df["ema50"] * 100

    # 52-week high/low
    df["high_52w"] = df["high"].rolling(252, min_periods=50).max()
    df["low_52w"]  = df["low"].rolling(252, min_periods=50).min()

    # Supertrend (length=7, multiplier=3.0 - standard settings)
    # Direction: 1 = bullish (price above line), -1 = bearish (price below line)
    st = ta.supertrend(df["high"], df["low"], df["close"], length=7, multiplier=3.0)
    if st is not None and not st.empty:
        _cols = st.columns.tolist()
        # SUPERTd_ = direction, SUPERT_ (no d/l/s suffix) = line value
        _dir = next((c for c in _cols if c.startswith("SUPERTd_")), None)
        _val = next((c for c in _cols if c.startswith("SUPERT_")
                     and "d_" not in c and "l_" not in c and "s_" not in c), None)
        if _dir: df["supertrend_dir"] = st[_dir]
        if _val: df["supertrend"]     = st[_val]

    return df


def get_stage(df: pd.DataFrame) -> str:
    """Classify stock phase: Stage1 / Stage2 / Stage3."""
    last = df.iloc[-1]
    close   = last["close"]
    ema20   = last.get("ema20")
    ema50   = last.get("ema50")
    rsi     = last.get("rsi")
    bb_wid  = last.get("bb_width")

    if pd.isna(ema20) or pd.isna(ema50):
        return "Unknown"

    if ema20 > ema50 and close > ema20:
        # check if parabolic (fast recent gains)
        recent_gain = (close - df["close"].iloc[-10]) / df["close"].iloc[-10] * 100
        if recent_gain > 20 and rsi and rsi > 70:
            return "Stage3"
        return "Stage2"
    elif abs(close - ema20) / ema20 < 0.03 and bb_wid and bb_wid < 5:
        return "Stage1"
    return "Stage1"
