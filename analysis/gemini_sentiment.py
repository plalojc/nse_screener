
# ============================================================
# analysis/gemini_sentiment.py – Gemini 2.5 Flash Post-Panel Validator
# ============================================================
# Post-panel validation step using Gemini 2.5 Flash + Google Search grounding.
# Runs AFTER the multi-LLM panel, only on CONFIRM/WEAK signals.
# Searches the web for real-time news and gives its own verdict.
# Uses an override table (same as Claude live validation) to modify panel verdicts.
#
# Toggle via USE_GEMINI_SENTIMENT=true in .env.
#
# SDK: google-genai (pip install google-genai)
# Free tier: 500 grounded searches/day, 10 RPM.
# Per-symbol per-day DB cache avoids duplicate API calls on re-runs.
# ============================================================

import json
import logging
import re
import sqlite3
import time
from datetime import datetime
from typing import Dict, List, Optional

from config import (
    DB_PATH,
    GEMINI_SENTIMENT_API_KEY,
    GEMINI_SENTIMENT_ENABLED,
    GEMINI_SENTIMENT_MODEL,
    GEMINI_SENTIMENT_RATE_DELAY,
)
from data.database import save_breakout_log

logger = logging.getLogger(__name__)


# ── Override Logic (PROTECTIVE — can only downgrade, never upgrade) ────────────
#
# Rationale: The multi-LLM panel is a thorough 3-agent analysis (TECH + SENT +
# RISK with debate).  Gemini is a quick web news search — positive news alone
# should NOT override technical/risk concerns that led to a WEAK panel verdict.
# Gemini's role is strictly a "red flag detector": it can DOWNGRADE a signal
# when it finds bad news, but it can NEVER UPGRADE a WEAK signal to CONFIRM.
# Only Claude (Step 4c, thorough live analysis) has authority to upgrade.
#
# Panel Verdict | Gemini Verdict | Final Result
# ───────────────────────────────────────────────
# CONFIRM       | CONFIRM        | CONFIRM   (news supports, no change)
# CONFIRM       | WEAK           | CONFIRM   (neutral news doesn't invalidate technicals)
# CONFIRM       | REJECT         | WEAK      (bad news found → downgrade for safety)
# WEAK          | CONFIRM        | WEAK      (good news can't fix technical/risk issues)
# WEAK          | WEAK           | WEAK      (no change)
# WEAK          | REJECT         | REJECT    (bad news confirms panel weakness)

_OVERRIDE_TABLE = {
    ("CONFIRM", "CONFIRM"): "CONFIRM",
    ("CONFIRM", "WEAK"):    "CONFIRM",
    ("CONFIRM", "REJECT"):  "WEAK",
    ("WEAK",    "CONFIRM"): "WEAK",
    ("WEAK",    "WEAK"):    "WEAK",
    ("WEAK",    "REJECT"):  "REJECT",
}


def _apply_override(panel_verdict: str, gemini_verdict: str) -> str:
    """Return final verdict after combining panel + Gemini verdicts."""
    return _OVERRIDE_TABLE.get(
        (panel_verdict.upper(), gemini_verdict.upper()),
        panel_verdict,  # fallback: keep panel verdict if combo not in table
    )


# ── Prompt for Gemini ────────────────────────────────────────────────────

_SENTIMENT_PROMPT = """
You are a financial news sentiment analyst for NSE India stocks.
Search the web for the LATEST news (last 48 hours) about {symbol} on NSE India.

Focus on:
1. Recent earnings, quarterly results, order wins, contract announcements
2. Analyst upgrades/downgrades, target price changes
3. FII/DII activity, promoter buying/selling/pledging
4. SEBI notices, regulatory actions, fraud allegations
5. Sector-wide news that affects this stock

After searching, return ONLY a valid JSON object (no markdown, no code fences):
{{
  "sentiment": "BULLISH or BEARISH or NEUTRAL",
  "confidence": 1-10,
  "reasoning": "2-3 sentences summarizing what you found",
  "articles": [
    {{
      "title": "headline of the article",
      "source": "publication name",
      "sentiment": "positive or negative or neutral"
    }}
  ]
}}

Rules:
- If you find POSITIVE catalysts (earnings beat, upgrade, order win): sentiment BULLISH
- If you find NEGATIVE news (downgrade, SEBI probe, loss, fraud): sentiment BEARISH
- If you find NO relevant recent news or mixed signals: sentiment NEUTRAL, confidence 4-5
- Include up to 5 most relevant articles in the articles array
- Always cite the actual source name (e.g., "Economic Times", "Moneycontrol")
"""


# ── DB cache ─────────────────────────────────────────────────────────────

def _get_cached(symbol: str, scan_date: str) -> Optional[dict]:
    """Return cached Gemini sentiment report for (symbol, date), or None."""
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT response_json FROM gemini_sentiment_cache "
            "WHERE symbol = ? AND scan_date = ?",
            (symbol, scan_date),
        ).fetchone()
        conn.close()
        if row and row[0]:
            return json.loads(row[0])
    except Exception as e:
        logger.debug(f"[GeminiSent] Cache read error for {symbol}: {e}")
    return None


def _save_cache(symbol: str, scan_date: str, data: dict):
    """Persist Gemini sentiment report to DB cache."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT OR REPLACE INTO gemini_sentiment_cache "
            "(symbol, scan_date, response_json, fetched_at) VALUES (?, ?, ?, ?)",
            (symbol, scan_date, json.dumps(data), datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.debug(f"[GeminiSent] Cache write error for {symbol}: {e}")


# ── API call ─────────────────────────────────────────────────────────────

def _call_gemini(symbol: str) -> Optional[dict]:
    """
    Call Gemini 2.5 Flash with Google Search grounding for a single symbol.
    Returns parsed sentiment dict or None.
    """
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        logger.warning("[GeminiSent] google-genai package not installed. "
                       "Run: pip install google-genai")
        return None

    if not GEMINI_SENTIMENT_API_KEY:
        logger.warning("[GeminiSent] GEMINI_SENTIMENT_API_KEY not set in .env")
        return None

    client = genai.Client(api_key=GEMINI_SENTIMENT_API_KEY)
    prompt = _SENTIMENT_PROMPT.format(symbol=symbol)

    MAX_RETRIES = 3
    for retry in range(MAX_RETRIES):
        try:
            response = client.models.generate_content(
                model=GEMINI_SENTIMENT_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                ),
            )

            # Safely extract text — response.text can throw if blocked/empty
            raw_text = ""
            try:
                raw_text = response.text or ""
            except (ValueError, AttributeError):
                # Gemini may block response or return empty candidates
                logger.warning(f"[GeminiSent] Empty/blocked response for {symbol}")
                return None

            if not raw_text.strip():
                logger.warning(f"[GeminiSent] Empty response text for {symbol}")
                return None

            # Extract grounding sources if available
            sources = _extract_grounding_sources(response)

            # Parse JSON from response
            parsed = _parse_json_response(raw_text.strip())
            if parsed:
                parsed["_grounding_sources"] = sources
                return parsed

            logger.warning(f"[GeminiSent] Could not parse JSON for {symbol}")
            return None

        except Exception as e:
            err_str = str(e).lower()

            # ── Auth errors (401/403) — likely prepayment needed ─────────
            if "401" in err_str or "403" in err_str or "permission" in err_str \
                    or "api_key" in err_str or "invalid" in err_str:
                logger.error(
                    f"[GeminiSent] AUTH ERROR for {symbol}: {e}\n"
                    "  → Check your GEMINI_SENTIMENT_API_KEY in .env\n"
                    "  → If Tier 1: go to https://aistudio.google.com/apikey "
                    "and check if 'Action needed' appears (prepayment required)\n"
                    "  → Verify the key is not from a deprecated project"
                )
                return None  # don't retry auth errors

            # ── Rate limit (429 / RESOURCE_EXHAUSTED) — retry with backoff
            if "429" in err_str or "resource_exhausted" in err_str \
                    or "rate" in err_str or "quota" in err_str:
                wait = min(4 * (2 ** retry), 30)  # 4s, 8s, 16s
                logger.warning(
                    f"[GeminiSent] Rate limit for {symbol} "
                    f"(attempt {retry + 1}/{MAX_RETRIES}), waiting {wait}s"
                )
                time.sleep(wait)
                continue

            # ── Server errors (500/503/UNAVAILABLE) — retry with backoff
            if "500" in err_str or "503" in err_str or "unavailable" in err_str \
                    or "internal" in err_str:
                wait = min(4 * (2 ** retry), 30)
                logger.warning(
                    f"[GeminiSent] Server error for {symbol} "
                    f"(attempt {retry + 1}/{MAX_RETRIES}), waiting {wait}s: {e}"
                )
                time.sleep(wait)
                continue

            # ── Other errors — log and don't retry
            logger.warning(f"[GeminiSent] API error for {symbol}: {e}")
            return None

    logger.warning(f"[GeminiSent] All retries exhausted for {symbol}")
    return None


def _extract_grounding_sources(response) -> List[Dict]:
    """Extract grounding source URLs/titles from Gemini response metadata."""
    sources = []
    try:
        candidates = getattr(response, "candidates", None)
        if not candidates:
            return sources
        metadata = getattr(candidates[0], "grounding_metadata", None)
        if not metadata:
            return sources
        chunks = getattr(metadata, "grounding_chunks", None) or []
        for chunk in chunks:
            web = getattr(chunk, "web", None)
            if web:
                sources.append({
                    "title": getattr(web, "title", "") or "",
                    "uri":   getattr(web, "uri", "") or "",
                })
    except Exception:
        pass
    return sources


def _parse_json_response(text: str) -> Optional[dict]:
    """Parse JSON from Gemini response, handling markdown fences."""
    if not text:
        return None

    # Strip markdown code fences if present
    cleaned = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE)
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object in the text
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None


# ── Response normalization ───────────────────────────────────────────────

def _normalize_report(parsed: dict) -> dict:
    """
    Normalize Gemini's parsed JSON into a structured sentiment report.
    Maps BULLISH/BEARISH/NEUTRAL to CONFIRM/WEAK/REJECT verdicts.
    """
    sentiment = (parsed.get("sentiment") or "NEUTRAL").upper()
    confidence = int(parsed.get("confidence") or 5)
    reasoning = parsed.get("reasoning") or ""

    # Normalize sentiment to score (-1.0 to +1.0)
    if sentiment == "BULLISH":
        avg_score = min(confidence / 10.0, 1.0)
    elif sentiment == "BEARISH":
        avg_score = max(-confidence / 10.0, -1.0)
    else:
        avg_score = 0.0

    # Map sentiment to verdict (BULLISH->CONFIRM, BEARISH->REJECT, NEUTRAL->WEAK)
    if sentiment == "BULLISH":
        verdict = "CONFIRM"
    elif sentiment == "BEARISH":
        verdict = "REJECT"
    else:
        verdict = "WEAK"

    # Normalize articles
    articles: List[Dict] = []
    for a in parsed.get("articles", []):
        art_sent = (a.get("sentiment") or "neutral").lower()
        if art_sent == "positive":
            art_score = 0.5
        elif art_sent == "negative":
            art_score = -0.5
        else:
            art_score = 0.0

        articles.append({
            "title":           a.get("title", "")[:100],
            "source":          a.get("source", ""),
            "sentiment_score": art_score,
        })

    # Merge grounding sources into articles if we have fewer articles
    grounding = parsed.get("_grounding_sources", [])
    seen_titles = {a["title"].lower() for a in articles}
    for gs in grounding:
        title = gs.get("title", "")
        if title.lower() not in seen_titles and len(articles) < 5:
            articles.append({
                "title":           title[:100],
                "source":          gs.get("uri", ""),
                "sentiment_score": 0.0,
            })
            seen_titles.add(title.lower())

    return {
        "article_count":      len(articles),
        "articles":           articles,
        "avg_sentiment":      round(avg_score, 3),
        "dominant_sentiment": sentiment,          # BULLISH / BEARISH / NEUTRAL
        "verdict":            verdict,             # CONFIRM / WEAK / REJECT
        "gemini_reasoning":   reasoning[:300],
        "confidence":         confidence,
        "source":             "Gemini",
    }


# ── Single-symbol sentiment fetch (cache-first) ─────────────────────────

def get_gemini_sentiment(symbol: str, scan_date: str) -> dict:
    """
    Fetch Gemini grounded news sentiment for a symbol (cache-first).

    Returns structured dict (see _normalize_report) or empty dict
    when disabled, API key missing, or any failure occurs.
    Uses per-symbol per-day DB cache to respect free-tier limits.
    """
    if not GEMINI_SENTIMENT_ENABLED or not GEMINI_SENTIMENT_API_KEY:
        return {}

    # ── Cache check ──────────────────────────────────────────────────
    cached = _get_cached(symbol, scan_date)
    if cached is not None:
        logger.debug(f"[GeminiSent] {symbol} -> cached")
        return cached

    # ── API call ─────────────────────────────────────────────────────
    parsed = _call_gemini(symbol)
    if parsed is None:
        return {}

    # ── Normalize & cache ────────────────────────────────────────────
    report = _normalize_report(parsed)
    _save_cache(symbol, scan_date, report)

    # Rate-limit: delay between calls
    if GEMINI_SENTIMENT_RATE_DELAY > 0:
        time.sleep(GEMINI_SENTIMENT_RATE_DELAY)

    return report


# ── Batch Validation (public API — post-panel validator) ────────────────

def validate_signals_gemini(signals: list, scan_date: str):
    """
    Post-panel validation using Gemini 2.5 Flash + Google Search grounding.
    Only processes CONFIRM/WEAK signals (REJECTs are skipped to save quota).

    Follows the same pattern as live_validator.py (Claude live validation).

    Mutates each signal dict in-place:
      - sig["gemini_verdict"]    = CONFIRM / WEAK / REJECT / SKIPPED
      - sig["gemini_confidence"] = 1-10
      - sig["gemini_reasoning"]  = string citing news sources found
      - sig["llm_verdict"]       = may be overridden by Gemini result

    Also persists Gemini fields to breakout_log via save_breakout_log().
    """
    try:
        from colorama import Fore, Style
    except ImportError:
        class _F:
            GREEN = YELLOW = RED = CYAN = MAGENTA = ""
        class _S:
            RESET_ALL = ""
        Fore, Style = _F(), _S()

    total = len(signals)
    overrides = []
    cached_count = 0
    api_count    = 0

    for idx, sig in enumerate(signals, 1):
        symbol = sig.get("symbol", "?")
        panel_verdict = sig.get("llm_verdict", "SKIPPED")

        # Only validate CONFIRM and WEAK (skip REJECTs)
        if panel_verdict not in ("CONFIRM", "WEAK"):
            sig["gemini_verdict"]    = "SKIPPED"
            sig["gemini_confidence"] = None
            sig["gemini_reasoning"]  = "Panel verdict was REJECT/SKIPPED"
            continue

        # Cache hit — already Gemini-validated today (loaded from breakout_log cache)
        existing_gemini = sig.get("gemini_verdict")
        if existing_gemini and existing_gemini not in ("SKIPPED", "", None):
            cached_count += 1
            if existing_gemini == "CONFIRM":
                v_color = Fore.GREEN
            elif existing_gemini == "REJECT":
                v_color = Fore.RED
            else:
                v_color = Fore.YELLOW
            print(
                f"  [Gemini {idx}/{total}] {symbol:<15} -> "
                f"{v_color}{existing_gemini:<7}{Style.RESET_ALL} (cached)"
            )
            continue

        # Cache miss — call Gemini with Google Search grounding
        report = get_gemini_sentiment(symbol, scan_date)

        if not report:
            # API call failed or disabled
            sig["gemini_verdict"]    = "SKIPPED"
            sig["gemini_confidence"] = None
            sig["gemini_reasoning"]  = "Gemini call failed or unavailable"
            print(f"  [Gemini {idx}/{total}] {symbol:<15} -> SKIPPED")
            # Persist to DB
            save_breakout_log(scan_date, sig)
            continue

        api_count += 1

        # Map Gemini report to verdict
        gemini_verdict    = report.get("verdict", "WEAK")
        gemini_confidence = report.get("confidence", 5)
        gemini_reasoning  = report.get("gemini_reasoning", "")

        sig["gemini_verdict"]    = gemini_verdict
        sig["gemini_confidence"] = gemini_confidence
        sig["gemini_reasoning"]  = gemini_reasoning

        # Apply override logic
        if gemini_verdict != "SKIPPED":
            original = panel_verdict
            final = _apply_override(panel_verdict, gemini_verdict)

            # Override the main verdict if changed
            if final != original:
                sig["llm_verdict"] = final
                overrides.append(f"{original}->{final}")

            # Color the output
            if gemini_verdict == "CONFIRM":
                v_color = Fore.GREEN
            elif gemini_verdict == "REJECT":
                v_color = Fore.RED
            else:
                v_color = Fore.YELLOW

            conf_str = f"conf={gemini_confidence}/10" if gemini_confidence else ""
            reason_short = gemini_reasoning[:60] if gemini_reasoning else ""

            print(
                f"  [Gemini {idx}/{total}] {symbol:<15} -> "
                f"{v_color}{gemini_verdict:<7}{Style.RESET_ALL} "
                f"{conf_str} ({reason_short})"
            )
        else:
            print(f"  [Gemini {idx}/{total}] {symbol:<15} -> SKIPPED")

        # Persist to DB
        save_breakout_log(scan_date, sig)

    # Summary
    override_str = f"Overrides: {', '.join(overrides)}" if overrides else "No overrides"
    print(
        f"  [Gemini] Done. API calls: {api_count} | Cached: {cached_count} | {override_str}"
    )
