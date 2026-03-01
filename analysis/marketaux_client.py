"""
MarketAux.com News/Sentiment API client (pluggable).

Optional enrichment layer for the SENTIMENT agent.  Fetches entity-level
sentiment scores for NSE stocks from MarketAux and formats them for the
LLM prompt.  Toggle via USE_MARKETAUX=true in .env.

• Free tier: 100 requests/day, 3 articles per request.
• Supports NSE stocks with .NS suffix (e.g. RELIANCE.NS).
• Per-symbol per-day DB cache avoids duplicate API calls on re-runs.
"""

import json
import logging
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import requests

from config import (
    DB_PATH,
    MARKETAUX_API_KEY,
    MARKETAUX_ENABLED,
    MARKETAUX_MAX_ARTICLES,
    MARKETAUX_RATE_DELAY,
)

logger = logging.getLogger(__name__)

_API_BASE = "https://api.marketaux.com/v1/news/all"


# ── Symbol conversion ────────────────────────────────────────────────────

def _nse_to_marketaux_symbol(symbol: str) -> str:
    """Convert internal NSE symbol to MarketAux format: RELIANCE -> RELIANCE.NS"""
    if symbol.endswith(".NS"):
        return symbol
    return f"{symbol}.NS"


# ── DB cache ─────────────────────────────────────────────────────────────

def _get_cached(symbol: str, scan_date: str) -> Optional[dict]:
    """Return cached MarketAux report for (symbol, date), or None."""
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT response_json FROM marketaux_cache "
            "WHERE symbol = ? AND scan_date = ?",
            (symbol, scan_date),
        ).fetchone()
        conn.close()
        if row and row[0]:
            return json.loads(row[0])
    except Exception as e:
        logger.debug(f"[MarketAux] Cache read error for {symbol}: {e}")
    return None


def _save_cache(symbol: str, scan_date: str, data: dict):
    """Persist MarketAux report to DB cache."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT OR REPLACE INTO marketaux_cache "
            "(symbol, scan_date, response_json, fetched_at) VALUES (?, ?, ?, ?)",
            (symbol, scan_date, json.dumps(data), datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.debug(f"[MarketAux] Cache write error for {symbol}: {e}")


# ── API call ─────────────────────────────────────────────────────────────

def _call_api(symbol: str) -> Optional[dict]:
    """Call MarketAux API for a single symbol.  Returns parsed JSON or None."""
    ma_symbol = _nse_to_marketaux_symbol(symbol)

    pub_after = (datetime.utcnow() - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M")

    params = {
        "api_token":       MARKETAUX_API_KEY,
        "symbols":         ma_symbol,
        "filter_entities": "true",
        "language":        "en",
        "published_after": pub_after,
        "limit":           MARKETAUX_MAX_ARTICLES,
    }

    MAX_RETRIES = 3
    for retry in range(MAX_RETRIES):
        try:
            resp = requests.get(_API_BASE, params=params, timeout=15)

            if resp.status_code == 429:
                wait = min(2 * (2 ** retry), 30)
                logger.warning(
                    f"[MarketAux] Rate limit for {symbol} "
                    f"(attempt {retry + 1}/{MAX_RETRIES}), waiting {wait}s"
                )
                time.sleep(wait)
                continue

            resp.raise_for_status()
            return resp.json()

        except requests.exceptions.HTTPError as e:
            logger.warning(f"[MarketAux] HTTP error for {symbol}: {e}")
            return None
        except requests.exceptions.RequestException as e:
            logger.warning(f"[MarketAux] Network error for {symbol}: {e}")
            return None
        except json.JSONDecodeError:
            logger.warning(f"[MarketAux] Invalid JSON response for {symbol}")
            return None

    logger.warning(f"[MarketAux] All retries exhausted for {symbol}")
    return None


# ── Response parsing ─────────────────────────────────────────────────────

def _extract_sentiment(raw: dict, symbol: str) -> dict:
    """
    Parse the MarketAux response into a structured sentiment report.

    Returns dict with keys:
        article_count, articles[], avg_sentiment, dominant_sentiment, source
    """
    ma_symbol = _nse_to_marketaux_symbol(symbol).upper()
    articles: List[Dict] = []

    for item in raw.get("data", []):
        title       = item.get("title", "")
        source      = item.get("source", "")
        description = item.get("description", "") or ""
        url         = item.get("url", "")
        published   = item.get("published_at", "")
        highlight   = item.get("highlight_score", 0) or 0

        # Find entity sentiment matching our symbol
        ent_score   = 0.0
        match_score = 0.0
        for ent in item.get("entities", []):
            ent_sym = (ent.get("symbol") or "").upper()
            if ent_sym == ma_symbol:
                ent_score   = float(ent.get("sentiment_score", 0) or 0)
                match_score = float(ent.get("match_score", 0) or 0)
                break

        articles.append({
            "title":           title,
            "source":          source,
            "description":     description[:200],
            "sentiment_score": ent_score,
            "match_score":     match_score,
            "highlight_score": highlight,
            "published_at":    published,
            "url":             url,
        })

    # Sort by highlight_score descending (most relevant first)
    articles.sort(key=lambda a: -(a.get("highlight_score") or 0))

    # Compute average sentiment
    if articles:
        avg = sum(a["sentiment_score"] for a in articles) / len(articles)
    else:
        avg = 0.0

    # Classify
    if avg > 0.15:
        dominant = "BULLISH"
    elif avg < -0.15:
        dominant = "BEARISH"
    else:
        dominant = "NEUTRAL"

    return {
        "article_count":      len(articles),
        "articles":           articles,
        "avg_sentiment":      round(avg, 3),
        "dominant_sentiment": dominant,
        "source":             "MarketAux",
    }


# ── Prompt formatting ────────────────────────────────────────────────────

def format_marketaux_for_prompt(report: dict) -> str:
    """
    Format MarketAux sentiment report as a text block for the SENTIMENT
    agent's LLM prompt.  Returns empty string if no data.
    """
    if not report or report.get("article_count", 0) == 0:
        return ""

    sign = "+" if report["avg_sentiment"] >= 0 else ""
    lines = [
        f"MARKETAUX SENTIMENT ({report['article_count']} article(s) | API-scored)",
        f"Avg Sentiment : {sign}{report['avg_sentiment']:.2f} (range -1.0 to +1.0)",
        f"Dominant      : {report['dominant_sentiment']}",
        "---",
    ]

    for i, a in enumerate(report.get("articles", [])[:5], 1):
        s_sign = "+" if a["sentiment_score"] >= 0 else ""
        title  = a.get("title", "")[:80]
        source = a.get("source", "?")
        lines.append(
            f"[{i}] {s_sign}{a['sentiment_score']:.2f} – "
            f"\"{title}\" [{source}]"
        )
        desc = a.get("description", "")
        if desc:
            lines.append(f"     {desc[:120]}")

    return "\n".join(lines)


# ── Public API ───────────────────────────────────────────────────────────

def get_marketaux_sentiment(symbol: str, scan_date: str) -> dict:
    """
    Fetch MarketAux sentiment for a symbol (cache-first).

    Returns structured dict (see _extract_sentiment) or empty dict
    when disabled, API key missing, or any failure occurs.
    Uses per-symbol per-day DB cache to respect free-tier limits.
    """
    if not MARKETAUX_ENABLED or not MARKETAUX_API_KEY:
        return {}

    # ── Cache check ──────────────────────────────────────────────────
    cached = _get_cached(symbol, scan_date)
    if cached is not None:
        logger.debug(f"[MarketAux] {symbol} -> cached")
        return cached

    # ── API call ─────────────────────────────────────────────────────
    raw = _call_api(symbol)
    if raw is None:
        return {}

    # ── Extract & cache ──────────────────────────────────────────────
    report = _extract_sentiment(raw, symbol)
    _save_cache(symbol, scan_date, report)

    # Rate-limit: small delay between calls
    if MARKETAUX_RATE_DELAY > 0:
        time.sleep(MARKETAUX_RATE_DELAY)

    return report
