# ============================================================
# analysis/catalyst_news.py - Resilient catalyst/news event fetcher
# ============================================================
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Iterable

import feedparser
import requests

from analysis.theme_mapper import match_policy_themes
from config import (
    CATALYST_LOOKBACK_DAYS,
    CATALYST_SOURCE_TIMEOUT,
    MAX_POLICY_SYMBOLS_PER_EVENT,
    MAX_PRICE,
    MIN_CATALYST_SCORE,
    MIN_NEWS_TECH_SCORE,
    MIN_NEWS_TURNOVER_CR,
    MIN_PRICE,
    NEWS_MAX_EMA20_EXTENSION_PCT,
)
from data.database import get_catalyst_events, save_catalyst_events


NSE_HOME = "https://www.nseindia.com"
NSE_ANNOUNCEMENTS_API = "https://www.nseindia.com/api/corporate-announcements"
PIB_RSS_FEEDS = (
    "https://www.pib.gov.in/ViewRss.aspx?lang=1&reg=6",
    "https://www.pib.gov.in/RssMain.aspx",
)


POSITIVE_KEYWORDS = {
    "BLOCK_DEAL": ("block deal", "bulk deal", "large deal"),
    "RESULTS": (
        "financial results", "quarterly results", "audited results",
        "unaudited results", "profit", "revenue", "ebitda", "pat",
        "margin expansion", "highest ever", "record revenue",
    ),
    "ORDER_WIN": (
        "order win", "order received", "contract", "letter of award",
        "loa", "work order", "purchase order", "tender", "award of",
    ),
    "EXPANSION": (
        "capacity expansion", "capex", "new plant", "commissioning",
        "acquisition", "joint venture", "strategic investment",
        "commercial production", "greenfield", "brownfield",
    ),
    "APPROVAL": (
        "approval", "usfda", "regulatory approval", "license",
        "authorisation", "authorization", "permission", "clearance",
    ),
    "CAPITAL_ACTION": (
        "buyback", "bonus", "stock split", "dividend", "fund raising",
        "preferential issue", "qip", "rights issue",
    ),
}

NEGATIVE_KEYWORDS = (
    "resignation of statutory auditor", "auditor resignation", "default",
    "fraud", "forensic audit", "penalty", "downgrade", "pledge",
    "insolvency", "winding up", "search and seizure", "order cancellation",
    "termination", "show cause notice",
)


def _clean_text(value: str | None) -> str:
    text = unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _safe_float(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_any_date(value: str | None) -> str:
    raw = _clean_text(value)
    if not raw:
        return datetime.now().date().isoformat()
    for fmt in (
        "%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%b-%Y",
        "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%d-%m-%Y",
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(raw[:len(datetime.now().strftime(fmt))], fmt).date().isoformat()
        except ValueError:
            pass
    try:
        return parsedate_to_datetime(raw).date().isoformat()
    except Exception:
        pass
    try:
        parsed = feedparser._parse_date(raw)
        if parsed:
            return datetime(*parsed[:6]).date().isoformat()
    except Exception:
        pass
    return datetime.now().date().isoformat()


def _categorise(text: str) -> tuple[str, int, int]:
    lowered = text.lower()
    if any(word in lowered for word in NEGATIVE_KEYWORDS):
        return "NEGATIVE_RISK", -5, 8
    for category, keywords in POSITIVE_KEYWORDS.items():
        if any(word in lowered for word in keywords):
            score = {
                "RESULTS": 9,
                "ORDER_WIN": 9,
                "BLOCK_DEAL": 8,
                "APPROVAL": 8,
                "EXPANSION": 7,
                "CAPITAL_ACTION": 5,
            }.get(category, 4)
            confidence = 8 if category in {"RESULTS", "ORDER_WIN", "APPROVAL"} else 7
            return category, score, confidence
    return "OTHER", 2, 4


def _summary_for(category: str, title: str) -> str:
    label = {
        "BLOCK_DEAL": "Block/bulk deal activity",
        "RESULTS": "Quarter/result-related announcement",
        "ORDER_WIN": "Order win or contract-related announcement",
        "EXPANSION": "Expansion/capex/acquisition-related announcement",
        "APPROVAL": "Approval/regulatory catalyst",
        "CAPITAL_ACTION": "Capital action such as buyback/bonus/dividend/fund raise",
        "GOV_POLICY": "Government policy/sector motivation",
        "NEGATIVE_RISK": "Negative/risk event",
    }.get(category, "Corporate announcement")
    return f"{label}: {title[:180]}"


def _nse_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,*/*",
        "Referer": f"{NSE_HOME}/companies-listing/corporate-filings-announcements",
    })
    try:
        session.get(NSE_HOME, timeout=CATALYST_SOURCE_TIMEOUT)
    except Exception:
        pass
    return session


def _event_key(event: dict) -> tuple:
    return (
        event.get("event_date"),
        event.get("symbol"),
        event.get("source"),
        event.get("title"),
    )


def _dedupe_events(events: list[dict]) -> list[dict]:
    best: dict[tuple, dict] = {}
    for event in events:
        key = _event_key(event)
        existing = best.get(key)
        if not existing or (event.get("score") or 0) > (existing.get("score") or 0):
            best[key] = event
    return list(best.values())


def fetch_nse_announcements(scan_date: str, universe_symbols: set[str]) -> list[dict]:
    end = datetime.strptime(scan_date, "%Y-%m-%d").date()
    start = end - timedelta(days=CATALYST_LOOKBACK_DAYS)
    params = {
        "index": "equities",
        "from_date": start.strftime("%d-%m-%Y"),
        "to_date": end.strftime("%d-%m-%Y"),
    }

    try:
        response = _nse_session().get(
            NSE_ANNOUNCEMENTS_API,
            params=params,
            timeout=CATALYST_SOURCE_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        print(f"  [Catalyst] NSE announcements unavailable: {exc}")
        return []

    rows = payload if isinstance(payload, list) else payload.get("data", [])
    events = []
    for row in rows:
        symbol = _clean_text(row.get("symbol") or row.get("sm_symbol") or row.get("SYMBOL")).upper()
        if not symbol or symbol not in universe_symbols:
            continue
        title = _clean_text(
            row.get("desc") or row.get("subject") or row.get("announcement") or row.get("attchmntText")
        )
        if not title:
            continue
        category, score, confidence = _categorise(title)
        if score < MIN_CATALYST_SCORE:
            continue
        url = _clean_text(row.get("attchmntFile") or row.get("url"))
        events.append({
            "event_date": _parse_any_date(row.get("an_dt") or row.get("date") or row.get("broadcast_time")),
            "symbol": symbol,
            "source": "NSE_ANNOUNCEMENT",
            "category": category,
            "title": title[:300],
            "summary": _summary_for(category, title),
            "url": url,
            "score": score,
            "confidence": confidence,
            "theme": None,
            "mapping_source": "DIRECT_COMPANY",
            "raw_payload": json.dumps(row, default=str)[:4000],
        })
    return events


def fetch_policy_events(scan_date: str, universe_symbols: set[str]) -> list[dict]:
    end = datetime.strptime(scan_date, "%Y-%m-%d").date()
    start = end - timedelta(days=CATALYST_LOOKBACK_DAYS)
    events = []

    for feed_url in PIB_RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
        except Exception as exc:
            print(f"  [Catalyst] PIB feed unavailable: {exc}")
            continue

        for entry in feed.entries[:100]:
            published = _parse_any_date(entry.get("published") or entry.get("updated"))
            try:
                event_day = datetime.strptime(published, "%Y-%m-%d").date()
            except ValueError:
                continue
            if not (start <= event_day <= end):
                continue

            title = _clean_text(entry.get("title"))
            body = _clean_text(entry.get("summary") or entry.get("description"))
            matches = match_policy_themes(title, body, universe_symbols)
            if not matches:
                continue

            for match in matches:
                for symbol in match.symbols[:MAX_POLICY_SYMBOLS_PER_EVENT]:
                    score = max(MIN_CATALYST_SCORE, match.score)
                    events.append({
                        "event_date": published,
                        "symbol": symbol,
                        "source": "PIB_POLICY",
                        "category": "GOV_POLICY",
                        "title": title[:300],
                        "summary": (
                            f"Policy theme - {match.label}: {title[:150]} "
                            f"(matched: {match.reason})"
                        ),
                        "url": _clean_text(entry.get("link")),
                        "score": score,
                        "confidence": match.confidence,
                        "theme": match.key,
                        "mapping_source": match.source,
                        "raw_payload": json.dumps({
                            "feed": feed_url,
                            "theme": match.key,
                            "theme_label": match.label,
                            "match_reason": match.reason,
                            "entry": dict(entry),
                        }, default=str)[:4000],
                    })
    return events


def fetch_and_store_catalysts(scan_date: str, universe_symbols: Iterable[str]) -> int:
    """Fetch all catalyst sources. Source failures never abort the scan."""
    try:
        universe = {str(s).upper().strip() for s in universe_symbols if str(s).strip()}
        if not universe:
            return 0

        events: list[dict] = []
        source_plan = (
            ("NSE announcements", fetch_nse_announcements),
            ("PIB policy feeds", fetch_policy_events),
        )
        for source_name, fetcher in source_plan:
            try:
                rows = fetcher(scan_date, universe)
                events.extend(rows)
                print(f"  [Catalyst] {source_name}: {len(rows)} event row(s)")
            except Exception as exc:
                print(f"  [Catalyst] {source_name} failed safely: {exc}")

        events = _dedupe_events(events)
        return save_catalyst_events(events)
    except Exception as exc:
        print(f"  [Catalyst] Catalyst fetch failed safely: {exc}")
        return 0


def get_catalyst_map(scan_date: str) -> dict[str, list[dict]]:
    try:
        events = get_catalyst_events(
            scan_date,
            lookback_days=CATALYST_LOOKBACK_DAYS,
            min_score=MIN_CATALYST_SCORE,
        )
    except Exception as exc:
        print(f"  [Catalyst] Could not load cached catalysts: {exc}")
        return {}

    result: dict[str, list[dict]] = {}
    for event in events:
        result.setdefault(event["symbol"], []).append(event)
    return result


def _best_catalyst(catalysts: list[dict]) -> dict | None:
    valid = [c for c in catalysts if str(c.get("category") or "").upper() != "NEGATIVE_RISK"]
    if not valid:
        return None
    return max(
        valid,
        key=lambda item: (
            _safe_int(item.get("score")),
            _safe_int(item.get("confidence")),
            str(item.get("event_date") or ""),
        ),
    )


def attach_best_catalyst(sig: dict, catalysts: list[dict]) -> dict:
    """Attach catalyst metadata to any technical signal for LLM context/ranking."""
    catalyst = _best_catalyst(catalysts)
    if not catalyst:
        return sig
    existing_score = _safe_int(sig.get("catalyst_score"))
    new_score = _safe_int(catalyst.get("score"))
    if existing_score and existing_score > new_score:
        return sig

    sig["catalyst_category"] = catalyst.get("category")
    sig["catalyst_summary"] = catalyst.get("summary")
    sig["catalyst_source"] = catalyst.get("source")
    sig["catalyst_url"] = catalyst.get("url")
    sig["catalyst_score"] = new_score
    sig["catalyst_confidence"] = _safe_int(catalyst.get("confidence"), 5)
    sig["catalyst_theme"] = catalyst.get("theme")
    sig["catalyst_mapping_source"] = catalyst.get("mapping_source")
    return sig


def _news_technical_score(last, stage: str) -> tuple[int, list[str]]:
    score = 0
    reasons = []
    close = _safe_float(last.get("close"))
    ema20 = _safe_float(last.get("ema20"))
    ema50 = _safe_float(last.get("ema50"))
    ema200 = _safe_float(last.get("ema200"))
    rsi = _safe_float(last.get("rsi"))
    vol_ratio = _safe_float(last.get("vol_ratio")) or 0
    turnover_cr = _safe_float(last.get("turnover_cr")) or 0
    close_range_pos = _safe_float(last.get("close_range_pos")) or 0
    high_52w = _safe_float(last.get("high_52w"))
    ema20_extension = _safe_float(last.get("ema20_extension_pct"))

    if stage == "Stage2":
        score += 4
        reasons.append("Stage2 trend")
    elif stage == "Stage1":
        score += 3
        reasons.append("Stage1 base")

    if close and ema20 and close > ema20:
        score += 1
        reasons.append("above EMA20")
    if close and ema20 and ema50 and close > ema20 > ema50:
        score += 2
        reasons.append("EMA20/50 bullish")
    elif close and ema50 and close > ema50:
        score += 1
        reasons.append("above EMA50")
    if close and ema200 and close > ema200:
        score += 2
        reasons.append("above EMA200")

    if rsi is not None:
        if 50 <= rsi <= 72:
            score += 2
            reasons.append(f"RSI {rsi:.0f}")
        elif 45 <= rsi <= 78:
            score += 1
            reasons.append(f"RSI {rsi:.0f}")

    if vol_ratio >= 1.5:
        score += 2
        reasons.append(f"volume {vol_ratio:.1f}x")
    elif vol_ratio >= 1.1:
        score += 1
        reasons.append(f"volume {vol_ratio:.1f}x")

    if close_range_pos >= 0.65:
        score += 1
        reasons.append("strong close")
    if turnover_cr >= 10:
        score += 2
        reasons.append("liquid")
    elif turnover_cr >= 5:
        score += 1
        reasons.append("tradable liquidity")
    if close and high_52w and high_52w > 0:
        near_high = (high_52w - close) / high_52w * 100
        if near_high <= 10:
            score += 2
            reasons.append(f"{near_high:.1f}% from 52W high")
        elif near_high <= 20:
            score += 1
            reasons.append(f"{near_high:.1f}% from 52W high")
    if ema20_extension is not None and ema20_extension <= 8:
        score += 1
        reasons.append("not extended")

    return score, reasons


def build_news_signal(symbol: str, df, catalysts: list[dict]) -> dict | None:
    if not catalysts or df is None or df.empty:
        return None
    catalyst = _best_catalyst(catalysts)
    if not catalyst:
        return None

    try:
        if "rsi" in df.columns:
            enriched = df
            from analysis.technical import get_stage
        else:
            from analysis.technical import add_indicators, get_stage
            enriched = add_indicators(df)
        last = enriched.iloc[-1]
        stage = get_stage(enriched)
    except Exception:
        return None

    close = _safe_float(last.get("close"))
    if close is None or not (MIN_PRICE <= close <= MAX_PRICE):
        return None

    turnover_cr = _safe_float(last.get("turnover_cr")) or 0
    if turnover_cr < MIN_NEWS_TURNOVER_CR:
        return None
    if stage == "Stage3":
        return None

    ema20_extension_pct = _safe_float(last.get("ema20_extension_pct"))
    if (
        ema20_extension_pct is not None
        and ema20_extension_pct > NEWS_MAX_EMA20_EXTENSION_PCT
    ):
        return None

    tech_score, tech_reasons = _news_technical_score(last, stage)
    if tech_score < MIN_NEWS_TECH_SCORE:
        return None

    catalyst_score = _safe_int(catalyst.get("score"))
    catalyst_confidence = _safe_int(catalyst.get("confidence"), 5)
    score = min(30, int(catalyst_score + tech_score + round(catalyst_confidence / 2)))

    ema20 = _safe_float(last.get("ema20"))
    ema50 = _safe_float(last.get("ema50"))
    ema200 = _safe_float(last.get("ema200"))
    atr14 = _safe_float(last.get("atr14"))
    high_52w = _safe_float(last.get("high_52w"))
    rsi = _safe_float(last.get("rsi"))
    vol_ratio = _safe_float(last.get("vol_ratio")) or 0
    macd_hist = _safe_float(last.get("macd_hist"))
    supertrend_dir = _safe_float(last.get("supertrend_dir"))
    close_range_pos = _safe_float(last.get("close_range_pos")) or 0
    day_range_atr = _safe_float(last.get("day_range_atr")) or 0

    return {
        "signal_type": "NEWS",
        "symbol": symbol,
        "close": round(close, 2),
        "rsi": round(rsi, 1) if rsi is not None else None,
        "vol_ratio": round(vol_ratio, 2),
        "score": score,
        "swing_score": score,
        "news_quality_score": tech_score,
        "stage": stage,
        "reasons": (
            f"{catalyst.get('summary') or catalyst.get('title') or 'News catalyst'}"
            f" | Chart: {', '.join(tech_reasons[:5])}"
        ),
        "ema20": round(ema20, 2) if ema20 is not None else None,
        "ema50": round(ema50, 2) if ema50 is not None else None,
        "ema200": round(ema200, 2) if ema200 is not None else None,
        "macd_hist": round(macd_hist, 4) if macd_hist is not None else None,
        "supertrend_dir": int(supertrend_dir) if supertrend_dir is not None else None,
        "atr14": round(atr14, 2) if atr14 is not None else None,
        "swing_low": None,
        "high_52w": round(high_52w, 2) if high_52w is not None else None,
        "turnover_cr": round(turnover_cr, 2),
        "entry_risk_pct": None,
        "ema20_extension_pct": round(ema20_extension_pct, 2)
                                if ema20_extension_pct is not None else None,
        "ema50_extension_pct": round((close - ema50) / ema50 * 100, 2)
                                if close and ema50 else None,
        "close_range_pos": round(close_range_pos, 2),
        "day_range_atr": round(day_range_atr, 2),
        "breakout_lookback": "news",
        "catalyst_category": catalyst.get("category"),
        "catalyst_summary": catalyst.get("summary"),
        "catalyst_source": catalyst.get("source"),
        "catalyst_url": catalyst.get("url"),
        "catalyst_score": catalyst_score,
        "catalyst_confidence": catalyst_confidence,
        "catalyst_theme": catalyst.get("theme"),
        "catalyst_mapping_source": catalyst.get("mapping_source"),
    }
