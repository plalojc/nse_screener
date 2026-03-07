
# ============================================================
# data/upstox_client.py – Upstox historical data fetcher
# ============================================================
import gzip
import json
import requests
import pandas as pd
from datetime import date, datetime, timedelta
from config import UPSTOX_ACCESS_TOKEN, UPSTOX_BASE_URL, UPSTOX_HIST_URL, LOOKBACK_DAYS, FILTER_ETFS


HEADERS = {
    "accept":        "application/json",
    "Authorization": f"Bearer {UPSTOX_ACCESS_TOKEN}"
}

# ── ETF detection heuristics ──────────────────────────────────────────────────
# Upstox NSE.json has no dedicated ETF field; both equities and ETFs carry
# instrument_type="EQ".  We use three layers to detect and exclude ETFs.
_ETF_NAME_KEYWORDS   = ("ETF", "BEES", "INDEX FUND", "FOF")
_ETF_SYMBOL_SUFFIXES = ("ETF", "BEES")
_ETF_SECURITY_TYPES  = ("ETF", "INDEX")


def _is_etf(item: dict) -> bool:
    """Return True if the instrument is an ETF/index fund to be excluded.
    Uses multi-layer heuristics because Upstox provides no dedicated ETF field."""
    # Layer 1: security_type field (future-proof if Upstox adds proper typing)
    if item.get("security_type", "").upper() in _ETF_SECURITY_TYPES:
        return True
    # Layer 2: name contains ETF-related keyword (catches e.g. "Nippon India Silver ETF")
    name = item.get("name", "").upper()
    if any(kw in name for kw in _ETF_NAME_KEYWORDS):
        return True
    # Layer 3: symbol ends with known ETF suffix (catches HEALTHIETF, GOLDBEES, NIFTYBEES)
    symbol = item.get("trading_symbol", "").upper()
    if any(symbol.endswith(sfx) for sfx in _ETF_SYMBOL_SUFFIXES):
        return True
    return False


# Module-level caches (loaded once per process)
_INSTRUMENT_MAP:      dict = {}   # trading_symbol -> instrument_key
_INSTRUMENT_NAME_MAP: dict = {}   # trading_symbol -> company name


def _load_instrument_map() -> dict:
    """
    Download NSE instruments JSON from Upstox and build:
      _INSTRUMENT_MAP      : { trading_symbol -> instrument_key }
      _INSTRUMENT_NAME_MAP : { trading_symbol -> company name }
    instrument_key format: 'NSE_EQ|<ISIN>'  (e.g. 'NSE_EQ|INE002A01018')
    Both caches are populated once per process lifetime.
    """
    global _INSTRUMENT_MAP, _INSTRUMENT_NAME_MAP
    if _INSTRUMENT_MAP:
        return _INSTRUMENT_MAP

    url = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
    print("[Instruments] Loading NSE instrument map from Upstox...")
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = json.loads(gzip.decompress(resp.content))
        eq_items = [item for item in data
                    if item.get("instrument_type") == "EQ"
                    and not (FILTER_ETFS and _is_etf(item))]
        _INSTRUMENT_MAP      = {item["trading_symbol"]: item["instrument_key"]         for item in eq_items}
        _INSTRUMENT_NAME_MAP = {item["trading_symbol"]: item.get("name", "")           for item in eq_items}
        etf_note = " (ETFs excluded)" if FILTER_ETFS else ""
        print(f"[Instruments] Loaded {len(_INSTRUMENT_MAP)} EQ instruments{etf_note}.")
    except Exception as e:
        print(f"[Instruments] Failed to load instrument map: {e}")
        _INSTRUMENT_MAP      = {}
        _INSTRUMENT_NAME_MAP = {}

    return _INSTRUMENT_MAP


def get_instrument_name(symbol: str) -> str:
    """Return the company name for an NSE EQ symbol (empty string if unknown)."""
    _load_instrument_map()
    return _INSTRUMENT_NAME_MAP.get(symbol, "")


def get_instrument_key(symbol: str) -> str:
    """
    Return the correct Upstox instrument key for an NSE EQ symbol.
    Looks up the live instruments file (NSE_EQ|<ISIN>).
    Raises KeyError if the symbol is not found.
    """
    imap = _load_instrument_map()
    if symbol not in imap:
        raise KeyError(f"Symbol '{symbol}' not found in NSE instrument map.")
    return imap[symbol]


def _last_weekday(d: date) -> date:
    """Walk backwards from d until we land on Mon–Fri."""
    while d.weekday() >= 5:   # 5=Sat, 6=Sun
        d -= timedelta(days=1)
    return d


def fetch_historical(symbol: str, interval: str = "day", scan_date: str = None) -> pd.DataFrame:
    """
    Fetch historical OHLCV from Upstox v2 API.
    interval options: 1minute, 30minute, day, week, month

    scan_date: explicit 'YYYY-MM-DD' to use as to_date (useful for weekends /
               manual back-runs).  Omit to auto-detect the last trading day.

    Retries up to MAX_RETRIES days backwards to skip weekends / NSE holidays
    that cause 400 Bad Request responses.
    """
    try:
        instrument_key = get_instrument_key(symbol)
    except KeyError as e:
        print(f"[Upstox] {e}")
        return pd.DataFrame()

    MAX_RETRIES = 7  # covers extended holiday breaks

    if scan_date:
        to_dt = _last_weekday(datetime.strptime(scan_date, "%Y-%m-%d").date())
    else:
        to_dt = _last_weekday(date.today() - timedelta(days=1))

    for attempt in range(MAX_RETRIES):
        from_dt  = to_dt - timedelta(days=LOOKBACK_DAYS)
        to_str   = to_dt.strftime("%Y-%m-%d")
        from_str = from_dt.strftime("%Y-%m-%d")
        url = f"{UPSTOX_HIST_URL}/{instrument_key}/{interval}/{to_str}/{from_str}"

        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)

            if resp.status_code == 400:
                # Market was closed on to_dt (holiday) – try previous weekday
                to_dt = _last_weekday(to_dt - timedelta(days=1))
                continue

            resp.raise_for_status()
            data = resp.json()

            candles = data["data"]["candles"]
            df = pd.DataFrame(candles, columns=["date","open","high","low","close","volume","oi"])
            df["date"]   = pd.to_datetime(df["date"]).dt.date.astype(str)
            df["symbol"] = symbol
            df = df[["symbol","date","open","high","low","close","volume"]].sort_values("date")
            df = df.reset_index(drop=True)
            return df

        except Exception as e:
            print(f"[Upstox] Error fetching {symbol}: {e}")
            return pd.DataFrame()

    print(f"[Upstox] Could not fetch {symbol} after {MAX_RETRIES} retries "
          f"(all candidate dates were market holidays?)")
    return pd.DataFrame()


def fetch_nse_instruments() -> pd.DataFrame:
    """
    Return all NSE EQ instruments as a DataFrame using the live JSON file.
    Columns: symbol, name, instrument_key, lot_size, isin
    """
    imap_raw_url = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
    try:
        resp = requests.get(imap_raw_url, timeout=30)
        resp.raise_for_status()
        data = json.loads(gzip.decompress(resp.content))
        eq = [item for item in data
              if item.get("instrument_type") == "EQ"
              and not (FILTER_ETFS and _is_etf(item))]

        # Persist ETFs to the invalid_instruments blacklist.
        # Only inserts when the count in JSON differs from the count in DB
        # (first run, or NSE listed a new ETF) — avoids all DB work on daily re-runs.
        if FILTER_ETFS:
            etf_items = [item for item in data
                         if item.get("instrument_type") == "EQ" and _is_etf(item)]
            if etf_items:
                from data.database import bulk_add_invalid_instruments, get_conn as _get_db_conn
                _c = _get_db_conn()
                existing_etf_count = _c.execute(
                    "SELECT COUNT(*) FROM invalid_instruments WHERE source='AUTO_ETF'"
                ).fetchone()[0]
                _c.close()
                if existing_etf_count < len(etf_items):
                    # New ETFs found (first run or NSE listed a new fund)
                    etf_rows = [
                        {"symbol": x["trading_symbol"], "reason": "ETF", "source": "AUTO_ETF"}
                        for x in etf_items
                    ]
                    added = bulk_add_invalid_instruments(etf_rows)
                    if added:
                        print(f"  [Instruments] {added} new ETFs added to invalid_instruments blacklist.")

        df = pd.DataFrame(eq, columns=["trading_symbol","name","instrument_key","lot_size","isin"])
        df.rename(columns={"trading_symbol": "symbol"}, inplace=True)
        return df.reset_index(drop=True)
    except Exception as e:
        print(f"[Instruments] Error: {e}")
        return pd.DataFrame()


def fetch_ltp(symbols: list) -> dict:
    """
    Fetch Last Traded Price for a list of NSE symbols in a single API call.
    Uses Upstox v2 /market-quote/ltp endpoint.

    Returns {symbol: ltp_float} for symbols that responded.
    Missing symbols (e.g. market closed, bad key) are omitted from the dict.

    When the market is closed the endpoint still returns the last EOD price,
    so this is always more current than the historical-candle API.
    """
    if not symbols:
        return {}

    imap  = _load_instrument_map()
    # Build instrument_key list; skip unknown symbols silently
    keys  = [imap[s] for s in symbols if s in imap]
    s2key = {s: imap[s] for s in symbols if s in imap}
    key2s = {v: k for k, v in s2key.items()}

    if not keys:
        return {}

    # Upstox LTP endpoint accepts up to ~500 keys as comma-separated query param
    result = {}
    CHUNK  = 100   # safe batch size
    for i in range(0, len(keys), CHUNK):
        batch = keys[i : i + CHUNK]
        params = {"instrument_key": ",".join(batch)}
        try:
            resp = requests.get(
                f"{UPSTOX_BASE_URL}/market-quote/ltp",
                headers=HEADERS, params=params, timeout=10
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            for ikey, info in data.items():
                # Upstox may return key with or without exchange prefix in response
                sym = key2s.get(ikey) or key2s.get(ikey.split("|")[-1])
                ltp = info.get("last_price")
                if sym and ltp is not None:
                    result[sym] = float(ltp)
        except Exception as e:
            print(f"[Upstox LTP] Error for batch starting at {i}: {e}")

    return result
