
# ============================================================
# analysis/gemini_validator.py – Gemini Direct Validator
# ============================================================
# Replaces the multi-LLM panel with ONE focused Gemini call
# + Google Search grounding per signal.
#
# Why better than the 4-agent panel for this use case:
#   • 1 API call vs 4  →  4× less cost, latency, and noise
#   • Google Search grounding  →  live NSE news, SEBI notices, events
#   • Single coherent reasoning chain (no debate randomness)
#   • Gemini 2.5 Flash: fast/free  |  Gemini 2.5 Pro: highest accuracy
#
# Pipeline position (replaces Step 4 in screener_agent.py):
#   Rule-based scanner  →  Gemini Direct Validator  →  TOP PICKS
#
# Because Gemini searches the web live, Steps 4b (Gemini sentiment)
# and 4c (Claude live validation) are automatically skipped when
# USE_GEMINI_VALIDATOR=true — they would be redundant.
#
# Toggle : USE_GEMINI_VALIDATOR=true in .env
# API key: GEMINI_VALIDATOR_API_KEY  (falls back to GEMINI_SENTIMENT_API_KEY)
# Model  : GEMINI_VALIDATOR_MODEL    (default: gemini-2.5-flash)
# Rate   : GEMINI_VALIDATOR_RATE_DELAY seconds between calls
#          Free tier : 10 RPM  → set delay to 6.0
#          Tier 1    : 150 RPM → set delay to 0.4
# ============================================================

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
import time
from typing import Optional

from colorama import Fore, Style

from config import (
    ATR_SL_MULTIPLIER,
    GEMINI_VALIDATOR_API_KEY,
    GEMINI_VALIDATOR_CONCURRENCY,
    GEMINI_VALIDATOR_MODEL,
    GEMINI_VALIDATOR_RATE_DELAY,
    STOP_LOSS_PCT,
)
from data.database import add_invalid_instrument, get_llm_verdict_cache, save_breakout_log

logger = logging.getLogger(__name__)
if not logger.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setLevel(logging.WARNING)
    logger.addHandler(_h)
    logger.setLevel(logging.WARNING)


# ── Prompt ────────────────────────────────────────────────────────────────────

def _build_prompt(sig: dict) -> str:
    close     = sig.get("close", 0) or 0
    atr14     = sig.get("atr14") or 0
    swing_low = sig.get("swing_low") or 0

    # Compute SL / TP exactly as the screener does
    sl_atr    = round(close - ATR_SL_MULTIPLIER * atr14, 2) if atr14 > 0 else None
    sl_swing  = round(swing_low * 0.99, 2) if swing_low else None
    cands     = [x for x in [sl_atr, sl_swing] if x is not None and x < close]
    sl        = max(cands) if cands else round(close * (1 - STOP_LOSS_PCT / 100), 2)
    risk      = close - sl
    tp        = round(close + risk * 2, 2)
    sl_pct    = round(risk / close * 100, 1) if close else 0
    tp_pct    = round((tp - close) / close * 100, 1) if close else 0

    ema200_line = (
        f"EMA200      : ₹{sig['ema200']:.2f}"
        if sig.get("ema200") else "EMA200      : N/A"
    )

    st_dir = sig.get("supertrend_dir")
    st_desc = (
        "BULLISH" if st_dir == 1 else
        "BEARISH" if st_dir == -1 else "N/A"
    )

    macd = sig.get("macd_hist")
    macd_desc = (
        f"{macd:.4f} ({'bullish crossover' if macd and macd > 0 else 'bearish'})"
        if macd is not None else "N/A"
    )

    # Include RSS news headlines already fetched by the screener
    raw_news = sig.get("news") or []
    news_lines = "\n".join(
        f"  • {item['title'] if isinstance(item, dict) else str(item)}"
        for item in raw_news[:5]
    ) or "  None cached from RSS feeds."

    return f"""
You are a senior NSE India equity analyst. Validate the breakout signal below.
Use Google Search to find LIVE news and events for {sig.get('symbol')} NSE India.

═══ TECHNICAL SIGNAL (rule-based scanner) ════════════════════
Symbol      : {sig.get('symbol')}  |  Date: {sig.get('scan_date', 'today')}
Signal      : {sig.get('signal_type', 'BREAKOUT')}  |  Stage: {sig.get('stage')}
Score       : {sig.get('score', 0)}  (min to pass: 6; strong setup: ≥10)
Close Price : ₹{close}

TREND & INDICATORS
  EMA20      : ₹{sig.get('ema20') or 'N/A'}
  EMA50      : ₹{sig.get('ema50') or 'N/A'}
  {ema200_line}
  RSI (14)   : {sig.get('rsi') or 'N/A'}  (scanner range: 55–80; overbought >80)
  Vol Ratio  : {sig.get('vol_ratio') or 'N/A'}x 20-day avg  (high conviction ≥1.8x)
  ATR14      : ₹{atr14 or 'N/A'}
  MACD Hist  : {macd_desc}
  Supertrend : {st_desc}
  Swing Low  : ₹{swing_low or 'N/A'}

TRADE SETUP
  Entry      : ₹{close}
  Stop Loss  : ₹{sl}  ({sl_pct}% below entry)
  Target     : ₹{tp}  ({tp_pct}% above, 2:1 R:R)

Scanner reasons: {sig.get('reasons', 'N/A')}

CACHED RSS NEWS HEADLINES (pre-fetched, may be 1-2 days old):
{news_lines}
══════════════════════════════════════════════════════════════

SEARCH TASK — search for "{sig.get('symbol')} NSE India stock news site:economictimes.com OR site:moneycontrol.com OR site:business-standard.com OR site:nseindia.com"
Also search: "{sig.get('symbol')} NSE earnings results order SEBI 2026"

Find (last 7 days):
  1. Earnings / quarterly results / revenue guidance
  2. Order wins / regulatory approvals / partnerships
  3. SEBI notices / promoter pledging / fraud / court orders
  4. FII/DII institutional buying or selling disclosures
  5. Analyst upgrades / downgrades / target price changes
  6. Sector-level news (policy, rate changes, peer results) affecting this stock

IMPORTANT: If you find NO relevant news, say so honestly — do NOT hallucinate events.

BEFORE answering, also verify: is {sig.get('symbol')} a regular NSE equity share, or is it a non-equity instrument?
Set "is_etf": true if it is ANY of the following — ETF, Index Fund, Liquid Fund, Debt Fund, Overnight Fund, Money Market Fund, Mutual Fund (any category), FoF (Fund of Funds), BeES product, Bond ETF, or any instrument that tracks an index/basket instead of being a single company stock.
Set "is_etf": false ONLY if it is a regular listed company (equity share) on NSE.

Return ONLY a JSON object (no markdown, no prose):
{{
  "verdict":      "CONFIRM" | "WEAK" | "REJECT",
  "confidence":   <integer 1-10>,
  "is_etf":       true | false,
  "reasoning":    "<2-3 sentences: technical strength assessment + key news found + final call>",
  "key_catalyst": "<most important news item found, or 'No significant news in search results'>",
  "key_risk":     "<single biggest risk to this trade>"
}}

VERDICT RULES:
  CONFIRM — Score ≥ 10, vol ≥ 1.8x, RSI 55–79, Stage2, AND no major negative news.
            Neutral news is fine; a positive catalyst strengthens conviction further.
  WEAK    — Score 6–9, OR vol < 1.8x, OR RSI borderline (>75), OR no catalyst found,
            OR mixed/conflicting news. Setup exists but lacks full conviction.
  REJECT  — Negative news found (SEBI probe, earnings miss, fraud, rating downgrade,
            promoter selling, order cancellation) OR technicals broken (score < 6,
            RSI > 80, price extended far above EMA50).

Default: WEAK (confidence 5) when news search returns nothing relevant.
""".strip()


# ── JSON parser ───────────────────────────────────────────────────────────────

def _parse_json(text: str) -> Optional[dict]:
    if not text:
        return None
    cleaned = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$",           "", cleaned, flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", cleaned)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return None


# ── Async rate limiter ───────────────────────────────────────────────────────

class _AsyncRateLimiter:
    """Sliding-window rate limiter: allows at most `rpm` calls per 60 s."""
    def __init__(self, rpm: int) -> None:
        self._rpm   = max(rpm, 1)
        self._slots: list[float] = []
        self._lock  = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            self._slots = [t for t in self._slots if now - t < 60.0]
            if len(self._slots) >= self._rpm:
                wait = 60.0 - (now - self._slots[0]) + 0.1
                await asyncio.sleep(wait)
                now = time.monotonic()
                self._slots = [t for t in self._slots if now - t < 60.0]
            self._slots.append(time.monotonic())


# ── Async single-signal API call ──────────────────────────────────────────────

async def _call_gemini_async(
    sig: dict,
    client,
    sem: asyncio.Semaphore,
    rate_lim: _AsyncRateLimiter,
) -> Optional[dict]:
    """Async Gemini call with Google Search grounding. Returns parsed dict or None."""
    from google.genai import types
    symbol = sig.get("symbol", "")
    prompt = _build_prompt(sig)

    async with sem:
        await rate_lim.acquire()
        MAX_RETRIES = 3
        for retry in range(MAX_RETRIES):
            try:
                response = await client.aio.models.generate_content(
                    model=GEMINI_VALIDATOR_MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        tools=[types.Tool(google_search=types.GoogleSearch())],
                    ),
                )
                try:
                    raw_text = response.text or ""
                except (ValueError, AttributeError):
                    logger.warning(f"[GeminiValidator] Blocked/empty response for {symbol}")
                    return None
                if not raw_text.strip():
                    logger.warning(f"[GeminiValidator] Empty response for {symbol}")
                    return None
                return _parse_json(raw_text.strip())

            except Exception as e:
                err = str(e).lower()
                if "401" in err or "403" in err or "permission" in err or "api_key" in err:
                    logger.error(
                        f"[GeminiValidator] AUTH ERROR for {symbol}: {e}\n"
                        "  → Check GEMINI_VALIDATOR_API_KEY in .env\n"
                        "  → https://aistudio.google.com/apikey"
                    )
                    return None  # no retry on auth errors
                if "429" in err or "resource_exhausted" in err or "quota" in err:
                    wait = min(6 * (2 ** retry), 60)
                    logger.warning(
                        f"[GeminiValidator] Rate limit for {symbol} "
                        f"(attempt {retry+1}/{MAX_RETRIES}), waiting {wait}s"
                    )
                    await asyncio.sleep(wait)
                    continue
                if "500" in err or "503" in err or "unavailable" in err:
                    wait = min(6 * (2 ** retry), 60)
                    logger.warning(
                        f"[GeminiValidator] Server error for {symbol} "
                        f"(attempt {retry+1}/{MAX_RETRIES}), waiting {wait}s: {e}"
                    )
                    await asyncio.sleep(wait)
                    continue
                logger.warning(f"[GeminiValidator] API error for {symbol}: {e}")
                return None

        logger.warning(f"[GeminiValidator] All retries exhausted for {symbol}")
        return None


# ── Async batch orchestrator ──────────────────────────────────────────────────

async def _validate_all_async(signals: list, scan_date: str) -> list:
    """Run all Gemini calls concurrently, bounded by RPM and CONCURRENCY."""
    from google import genai
    client     = genai.Client(api_key=GEMINI_VALIDATOR_API_KEY)
    rpm        = max(1, int(round(60.0 / GEMINI_VALIDATOR_RATE_DELAY)))
    sem        = asyncio.Semaphore(GEMINI_VALIDATOR_CONCURRENCY)
    rate_lim   = _AsyncRateLimiter(rpm)
    print_lock = asyncio.Lock()

    verdict_cache = get_llm_verdict_cache(scan_date)
    total         = len(signals)
    cache_count   = 0
    api_counter   = [0]  # mutable int shared across coroutines

    # ── Print cache hits first (synchronously) ──────────────────────────────
    for sig in signals:
        sig["scan_date"] = scan_date
        symbol = sig.get("symbol", "?")
        if symbol in verdict_cache:
            sig.update(verdict_cache[symbol])
            sig.setdefault("panel_method", "GEMINI_DIRECT")
            cache_count += 1
            verdict  = sig.get("llm_verdict", "?")
            conf     = sig.get("llm_confidence")
            conf_str = f" ({conf}/10)" if conf else ""
            if verdict == "CONFIRM":
                v_str = Fore.GREEN  + verdict + conf_str + Style.RESET_ALL
            elif verdict == "REJECT":
                v_str = Fore.RED    + verdict + conf_str + Style.RESET_ALL
            elif verdict == "WEAK":
                v_str = Fore.YELLOW + verdict + conf_str + Style.RESET_ALL
            else:
                v_str = verdict + conf_str
            print(f"  [Gemini cached] {symbol:<15} → {v_str}")

    to_api    = [s for s in signals if s.get("symbol") not in verdict_cache]
    api_total = len(to_api)

    # ── Concurrent processing ────────────────────────────────────────────────
    async def process_one(sig: dict) -> None:
        symbol = sig.get("symbol", "?")
        parsed = await _call_gemini_async(sig, client, sem, rate_lim)

        if parsed:
            # ── ETF / Fund auto-blacklist ─────────────────────────────────────
            # Covers: ETF, Index Fund, Liquid Fund, Debt Fund, Overnight Fund,
            # Money Market Fund, FoF, BeES, Bond ETF — anything not a company stock.
            if parsed.get("is_etf") is True:
                add_invalid_instrument(
                    symbol=symbol,
                    reason="ETF/Fund/Liquid Fund identified by Gemini Search",
                    source="GEMINI_SEARCH",
                )
                sig["llm_verdict"]    = "REJECT"
                sig["llm_confidence"] = 1
                sig["llm_reasoning"]  = "Auto-blacklisted: Gemini identified this as an ETF/Fund/Liquid Fund, not a regular equity."
                sig["panel_method"]   = "GEMINI_DIRECT"
                async with print_lock:
                    api_counter[0] += 1
                    idx = api_counter[0]
                    print(
                        f"  [Gemini {idx:>3}/{api_total}] {symbol:<15} "
                        + Fore.RED + "→ FUND BLACKLISTED" + Style.RESET_ALL
                    )
                return

            raw_verdict = str(parsed.get("verdict", "WEAK")).upper()
            verdict     = raw_verdict if raw_verdict in ("CONFIRM", "WEAK", "REJECT") else "WEAK"
            confidence  = int(parsed.get("confidence") or 5)
            catalyst    = parsed.get("key_catalyst", "")
            risk        = parsed.get("key_risk", "")
            base_reason = parsed.get("reasoning", "")
            extras = []
            if catalyst and catalyst.lower() not in ("n/a", "none", ""):
                extras.append(f"Catalyst: {catalyst}")
            if risk and risk.lower() not in ("n/a", "none", ""):
                extras.append(f"Risk: {risk}")
            reasoning = base_reason + (" | " + " | ".join(extras) if extras else "")
        else:
            verdict    = "WEAK"
            confidence = 4
            reasoning  = "Gemini API call failed — defaulting to WEAK"

        sig["llm_verdict"]    = verdict
        sig["llm_confidence"] = confidence
        sig["llm_reasoning"]  = reasoning[:500]
        sig["panel_method"]   = "GEMINI_DIRECT"

        async with print_lock:
            api_counter[0] += 1
            idx      = api_counter[0]
            conf_str = f" ({confidence}/10)"
            if verdict == "CONFIRM":
                v_str = Fore.GREEN  + verdict + conf_str + Style.RESET_ALL
            elif verdict == "REJECT":
                v_str = Fore.RED    + verdict + conf_str + Style.RESET_ALL
            else:
                v_str = Fore.YELLOW + verdict + conf_str + Style.RESET_ALL
            print(f"  [Gemini {idx:>3}/{api_total}] {symbol:<15} → {v_str}")

    await asyncio.gather(*[process_one(sig) for sig in to_api])

    print(f"\n  Gemini: {api_counter[0]} API call(s), {cache_count} from cache.")
    return signals


# ── Public API ────────────────────────────────────────────────────────────────

def validate_signals_gemini_direct(signals: list, scan_date: str) -> list:
    """
    Drop-in replacement for validate_signals_panel() / validate_signals_batch().

    All signals are validated concurrently (asyncio.gather) — up to
    GEMINI_VALIDATOR_CONCURRENCY calls in flight at once, throttled by a
    sliding-window rate limiter derived from GEMINI_VALIDATOR_RATE_DELAY.

    Speed comparison (20 signals, free tier 10 RPM):
      Before (sequential + sleep): ~200 s
      After  (async concurrent)  :  ~70 s  (~3× faster)
    Paid Tier 1 (150 RPM, delay=0.4): near-instant regardless of signal count.
    """
    if not GEMINI_VALIDATOR_API_KEY:
        print(Fore.RED + "\n[4/5] Gemini validation SKIPPED.")
        print(Fore.RED + "      Reason: GEMINI_VALIDATOR_API_KEY is not set.")
        print(Fore.RED + "      Fix   : Add GEMINI_VALIDATOR_API_KEY=your_key to .env")
        print(Fore.RED + "               (get key at https://aistudio.google.com/apikey)")
        for sig in signals:
            sig["scan_date"]      = scan_date
            sig["llm_verdict"]    = "SKIPPED"
            sig["llm_confidence"] = None
            sig["llm_reasoning"]  = "GEMINI_VALIDATOR_API_KEY not set"
            sig["panel_method"]   = "SKIPPED"
        return signals

    try:
        from google import genai  # noqa: F401 — verify installed
    except ImportError:
        print(Fore.RED + "\n[4/5] Gemini validation SKIPPED — google-genai not installed.")
        print(Fore.RED + "      Fix: pip install google-genai")
        for sig in signals:
            sig["scan_date"]      = scan_date
            sig["llm_verdict"]    = "SKIPPED"
            sig["llm_confidence"] = None
            sig["llm_reasoning"]  = "google-genai not installed"
            sig["panel_method"]   = "SKIPPED"
        return signals

    rpm = max(1, int(round(60.0 / GEMINI_VALIDATOR_RATE_DELAY)))
    print(
        f"  [Gemini] Validating {len(signals)} signal(s) — "
        f"concurrency={GEMINI_VALIDATOR_CONCURRENCY}, RPM={rpm}, "
        f"model={GEMINI_VALIDATOR_MODEL}"
    )
    return asyncio.run(_validate_all_async(signals, scan_date))
