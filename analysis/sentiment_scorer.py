
# ============================================================
# analysis/sentiment_scorer.py – Heuristic news sentiment scoring
# ============================================================
# Pure rule-based keyword scoring — zero LLM calls, ~1ms latency.
# Produces a SymbolSentimentReport that the Sentiment Agent LLM
# receives as pre-processed structured context (richer than raw headlines).
# ============================================================

import re
from dataclasses import dataclass, field
from typing import List


# ── Keyword Dictionaries ──────────────────────────────────────────────────────

_BULLISH_STRONG = {
    "profit", "profits", "earnings beat", "revenue surge", "order win", "orders won",
    "acquisition", "buyback", "dividend", "bonus", "results beat", "outperform",
    "upgrade", "target raised", "expansion", "new plant", "capacity addition",
    "regulatory approval", "fda approval", "contract won", "stake acquired",
    "ipo approved", "fundraise", "allotment", "qip success",
}

_BULLISH_MODERATE = {
    "growth", "revenue", "sales", "margin", "guidance raised", "positive outlook",
    "bullish", "rally", "momentum", "breakout", "recovery", "rebound",
    "strong", "beat", "exceed", "surplus", "gain", "rise", "climbs", "surges",
    "new high", "52 week", "record", "listing gains", "ipo listing",
}

_BEARISH_STRONG = {
    "fraud", "sebi probe", "sebi notice", "ed raid", "income tax raid", "it raid",
    "npa", "default", "debt restructuring", "insolvency", "nclt", "promoter pledging",
    "promoter pledge", "accounting irregularity", "restatement", "whistleblower",
    "scam", "bribery", "corruption", "embargo", "sanction", "recall", "fda rejection",
    "licence cancelled", "ban", "delisting", "demerger penalty", "penalty imposed",
}

_BEARISH_MODERATE = {
    "loss", "losses", "decline", "miss", "missed", "downgrade", "target cut",
    "below estimate", "weak quarter", "margin pressure", "debt", "concern",
    "warning", "risk", "volatile", "selloff", "fall", "drops", "slumps",
    "negative", "cut", "reduce", "selling pressure", "fii selling",
    "promoter selling", "block deal", "outflow",
}


def _classify_article(title: str, body: str, symbol: str) -> dict:
    """
    Score a single article using keyword matching.
    Returns dict: {sentiment, magnitude, relevance, matched_keywords}
    """
    text = (title + " " + body).lower()

    # Relevance: how directly does this article relate to the stock?
    sym_lower = symbol.lower()
    relevance = 3   # baseline (market news)
    if sym_lower in text:
        relevance = 9   # direct mention of ticker
    elif len(sym_lower) >= 4 and sym_lower[:4] in text:
        relevance = 6   # partial match (e.g. "TATA" in "Tata Motors")

    # Count keyword hits
    strong_bull = sum(1 for kw in _BULLISH_STRONG if kw in text)
    mod_bull    = sum(1 for kw in _BULLISH_MODERATE if kw in text)
    strong_bear = sum(1 for kw in _BEARISH_STRONG if kw in text)
    mod_bear    = sum(1 for kw in _BEARISH_MODERATE if kw in text)

    bull_score = strong_bull * 3 + mod_bull * 1
    bear_score = strong_bear * 3 + mod_bear * 1

    if bull_score == 0 and bear_score == 0:
        sentiment = "NEUTRAL"
        magnitude = 2
    elif bull_score > bear_score:
        sentiment = "BULLISH"
        magnitude = min(10, 2 + bull_score * 2)
    elif bear_score > bull_score:
        sentiment = "BEARISH"
        magnitude = min(10, 2 + bear_score * 2)
    else:
        sentiment = "NEUTRAL"
        magnitude = 3

    matched = []
    for kw in list(_BULLISH_STRONG) + list(_BULLISH_MODERATE):
        if kw in text:
            matched.append(f"+{kw}")
    for kw in list(_BEARISH_STRONG) + list(_BEARISH_MODERATE):
        if kw in text:
            matched.append(f"-{kw}")

    return {
        "sentiment":        sentiment,
        "magnitude":        magnitude,
        "relevance":        relevance,
        "matched_keywords": matched[:6],   # top 6 for display
    }


# ── Public API ────────────────────────────────────────────────────────────────

@dataclass
class ArticleSentiment:
    title:    str
    source:   str
    sentiment: str          # BULLISH | BEARISH | NEUTRAL
    magnitude: int          # 1-10
    relevance: int          # 1-10
    matched_keywords: List[str] = field(default_factory=list)


@dataclass
class SymbolSentimentReport:
    symbol:            str
    article_count:     int
    net_score:         float    # -1.0 to +1.0
    dominant_sentiment: str     # BULLISH | BEARISH | NEUTRAL
    confidence:        float    # 0.0 to 1.0
    articles:          List[ArticleSentiment] = field(default_factory=list)
    formatted_text:    str = ""  # pre-formatted block for LLM Sentiment Agent prompt


def score_news_for_symbol(symbol: str, news_items: List[dict]) -> SymbolSentimentReport:
    """
    Process a list of news dicts (each with 'title', 'source', optionally 'body')
    and return a SymbolSentimentReport.

    news_items format: [{"title": str, "source": str, "body": str (optional)}, ...]
    """
    if not news_items:
        report = SymbolSentimentReport(
            symbol=symbol, article_count=0, net_score=0.0,
            dominant_sentiment="NEUTRAL", confidence=0.0,
        )
        report.formatted_text = _format_empty(symbol)
        return report

    articles = []
    for item in news_items:
        title  = item.get("title", "")
        body   = item.get("body", "")
        source = item.get("source", "")
        scored = _classify_article(title, body, symbol)
        articles.append(ArticleSentiment(
            title=title, source=source,
            sentiment=scored["sentiment"],
            magnitude=scored["magnitude"],
            relevance=scored["relevance"],
            matched_keywords=scored["matched_keywords"],
        ))

    # Sort by relevance desc for display
    articles.sort(key=lambda a: -a.relevance)

    # Compute net score: signed, weighted by magnitude and relevance
    direction_map = {"BULLISH": 1, "NEUTRAL": 0, "BEARISH": -1}
    total_weight   = 0.0
    weighted_sum   = 0.0
    for a in articles:
        w = a.relevance * a.magnitude
        total_weight  += w
        weighted_sum  += direction_map[a.sentiment] * w

    net_score = round(weighted_sum / total_weight, 3) if total_weight > 0 else 0.0

    # Dominant sentiment
    counts = {"BULLISH": 0, "BEARISH": 0, "NEUTRAL": 0}
    for a in articles:
        counts[a.sentiment] += 1
    dominant = max(counts, key=lambda k: counts[k])

    # Confidence: based on agreement (all same sentiment = 1.0, mixed = low)
    n = len(articles)
    majority = counts[dominant]
    confidence = round(majority / n, 2) if n > 0 else 0.0

    report = SymbolSentimentReport(
        symbol=symbol,
        article_count=n,
        net_score=net_score,
        dominant_sentiment=dominant,
        confidence=confidence,
        articles=articles,
    )
    report.formatted_text = _format_report(report)
    return report


def _format_report(report: SymbolSentimentReport) -> str:
    """
    Format SymbolSentimentReport as a structured text block for the Sentiment Agent prompt.
    """
    sign = "+" if report.net_score >= 0 else ""
    lines = [
        f"SENTIMENT REPORT – {report.symbol} ({report.article_count} article(s))",
        f"Net Score    : {sign}{report.net_score:.2f} (range -1.0 to +1.0)",
        f"Dominant     : {report.dominant_sentiment}  |  Agreement: {report.confidence*100:.0f}%",
        "---",
    ]
    for i, a in enumerate(report.articles[:5], 1):
        kw_str = ", ".join(a.matched_keywords[:3]) if a.matched_keywords else "none"
        lines.append(
            f"[{i}] {a.sentiment}(mag:{a.magnitude}/10 rel:{a.relevance}/10) "
            f"– \"{a.title[:70]}\" [{a.source}]"
        )
        lines.append(f"     Keywords: {kw_str}")
    return "\n".join(lines)


def _format_empty(symbol: str) -> str:
    return (
        f"SENTIMENT REPORT – {symbol} (0 articles)\n"
        "No news found for this symbol. Treat as NEUTRAL with low confidence.\n"
        "Default to WEAK verdict unless technical setup is extremely compelling."
    )
