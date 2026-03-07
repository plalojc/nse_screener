
# ============================================================
# analysis/llm_panel.py – Multi-LLM Panel with Human-Like Reasoning
# ============================================================
#
# Architecture (inspired by TradingAgents 2024-2025 paper):
#   3 specialist agents run IN PARALLEL (ThreadPoolExecutor):
#     1. TECHNICAL Analyst  (llama-4-scout)  – chart patterns, indicators, stage
#     2. SENTIMENT Analyst  (llama-3.1-8b)   – news, catalysts, overhangs
#     3. RISK Manager       (llama-4-scout)  – stop loss quality, R:R, tail risks
#
#   Weighted consensus: TECH×0.40 + SENT×0.35 + RISK×0.25
#
#   Bull/Bear DEBATE triggered when agents strongly disagree:
#     Turn 1 → Bull Researcher  (llama-4-scout)    argues FOR
#     Turn 2 → Bear Researcher  (llama-4-scout)    argues AGAINST
#     Turn 3 → Fund Manager     (llama-4-maverick) final CONFIRM/REJECT
#
#   Rate-limit hardening: _call_llm() has exponential backoff (1→2→4→8s)
#   for 429 errors. PANEL_SEQUENTIAL_MODE=true runs agents one-at-a-time.
#
#   Full backward compatibility: always populates sig["llm_verdict"],
#   sig["llm_confidence"], sig["llm_reasoning"] so existing display
#   and reporting code works with zero changes.
# ============================================================

import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional, Dict, List

from config import (
    LLM_API_KEY, LLM_BASE_URL, LLM_TEMPERATURE,
    LLM_PANEL_TECH_MODEL, LLM_PANEL_SENT_MODEL, LLM_PANEL_RISK_MODEL,
    LLM_PANEL_MODERATOR_MODEL,
    LLM_PANEL_MAX_TOKENS, ATR_SL_MULTIPLIER, STOP_LOSS_PCT, MAX_OPEN_POSITIONS,
    PANEL_SEQUENTIAL_MODE, PANEL_AGENT_DELAY,
    PANEL_TECH_WEIGHT, PANEL_SENT_WEIGHT, PANEL_RISK_WEIGHT,
)

logger = logging.getLogger(__name__)
if not logger.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setLevel(logging.WARNING)
    logger.addHandler(_h)
    logger.setLevel(logging.WARNING)


# ── Consensus weights (must sum to 1.0) ──────────────────────────────────────
# Configurable via PANEL_TECH_WEIGHT / PANEL_SENT_WEIGHT / PANEL_RISK_WEIGHT in .env
# Default: TECH×0.50, SENT×0.20, RISK×0.30 (research-calibrated for sparse news coverage)
_AGENT_WEIGHTS = {
    "TECHNICAL": PANEL_TECH_WEIGHT,
    "SENTIMENT": PANEL_SENT_WEIGHT,
    "RISK":      PANEL_RISK_WEIGHT,
}
_VERDICT_SCORE = {"CONFIRM": 1.0, "WEAK": 0.5, "REJECT": 0.0}
_CONFIRM_THRESH = 0.65   # was 0.68 — narrowed grey zone from 30 pts to 23 pts
_WEAK_THRESH    = 0.42   # was 0.38


# ── Data Structures ───────────────────────────────────────────────────────────

@dataclass
class AgentVerdict:
    agent_name:  str
    verdict:     str           # CONFIRM | WEAK | REJECT
    confidence:  int           # 1-10
    reasoning:   str           # 2-3 sentence CoT chain
    bull_points: List[str] = field(default_factory=list)
    bear_points: List[str] = field(default_factory=list)
    key_concern: str = ""
    failed:      bool = False


@dataclass
class DebateResult:
    triggered:          bool = False
    bull_stance:        str  = ""
    bear_stance:        str  = ""
    moderator_verdict:  str  = "WEAK"
    moderator_confidence: int = 5
    moderator_reasoning: str  = ""
    debate_winner:      str  = ""


@dataclass
class PanelVerdict:
    # Core fields (same interface as existing single-LLM validator)
    llm_verdict:    str
    llm_confidence: int
    llm_reasoning:  str

    # Per-agent breakdown
    tech_verdict:    str = ""
    tech_confidence: int = 0
    tech_reasoning:  str = ""
    sent_verdict:    str = ""
    sent_confidence: int = 0
    sent_reasoning:  str = ""
    risk_verdict:    str = ""
    risk_confidence: int = 0
    risk_reasoning:  str = ""

    # Debate
    debate_triggered: bool = False
    debate_winner:    str  = ""
    debate_reasoning: str  = ""

    # Meta
    panel_method:   str   = "MULTI_LLM"
    weighted_score: float = 0.0

    # Patterns
    vcp_detected:       int = 0
    bull_flag_detected: int = 0
    pattern_score:      int = 0

    def to_dict(self) -> dict:
        return {
            "llm_verdict":      self.llm_verdict,
            "llm_confidence":   self.llm_confidence,
            "llm_reasoning":    self.llm_reasoning,
            "tech_verdict":     self.tech_verdict,
            "tech_confidence":  self.tech_confidence,
            "tech_reasoning":   self.tech_reasoning,
            "sent_verdict":     self.sent_verdict,
            "sent_confidence":  self.sent_confidence,
            "sent_reasoning":   self.sent_reasoning,
            "risk_verdict":     self.risk_verdict,
            "risk_confidence":  self.risk_confidence,
            "risk_reasoning":   self.risk_reasoning,
            "debate_triggered": int(self.debate_triggered),
            "debate_winner":    self.debate_winner,
            "debate_reasoning": self.debate_reasoning,
            "panel_method":     self.panel_method,
            "weighted_score":   self.weighted_score,
            "vcp_detected":     self.vcp_detected,
            "bull_flag_detected": self.bull_flag_detected,
            "pattern_score":    self.pattern_score,
        }


# ── System Prompts ────────────────────────────────────────────────────────────

_TECH_SYSTEM = """You are a veteran NSE (India) technical analyst with 15 years of experience
trading breakouts using Minervini, O'Neil, and IBD methodologies.

Your task: rigorously analyse the breakout signal data provided. Think step-by-step through
each technical factor. Be honest — an accurate WEAK or REJECT is worth more than a false CONFIRM.

Return ONLY a JSON object (no markdown, no prose):
{
  "verdict": "CONFIRM" | "WEAK" | "REJECT",
  "confidence": <integer 1-10>,
  "reasoning": "<2-3 sentences: strongest signal, main concern, final assessment>",
  "bull_points": ["<bullish factor 1>", "<bullish factor 2>"],
  "bear_points": ["<bearish factor 1>"],
  "key_concern": "<the single most important technical risk>"
}

Verdict guide:
  CONFIRM: Strong multi-indicator confluence (volume + RSI + EMA + MACD align). Stage2. Score >= 10.
  WEAK: Setup exists but one material flaw (RSI>75, low vol, single-indicator breakout, Stage1/3).
  REJECT: Technically broken (no volume, overbought RSI>80, extended from EMA50, contradictory signals).
"""

_SENT_SYSTEM = """You are an NSE equity research analyst specialising in news-driven fundamental
catalysts and their short-term (1-3 week) impact on stock price action.

Your task: evaluate whether the news/sentiment picture SUPPORTS or UNDERMINES this breakout.
Consider: catalysts (earnings, orders, approvals), overhangs (SEBI probe, pledging, dilution),
and timing alignment (does news explain the breakout, or is it unrelated?).

Return ONLY a JSON object (no markdown, no prose):
{
  "verdict": "CONFIRM" | "WEAK" | "REJECT",
  "confidence": <integer 1-10>,
  "reasoning": "<2-3 sentences: what news supports this, what are concerns, sentiment verdict>",
  "bull_points": ["<bullish catalyst 1>", "<bullish catalyst 2>"],
  "bear_points": ["<bearish news risk 1>"],
  "key_concern": "<biggest news/sentiment risk that could kill this trade>"
}

Calibration for NSE:
  CONFIRM: Clear positive catalyst aligned with breakout timing. No significant negative overhangs.
  WEAK: Neutral or mixed news. Technically driven with no strong fundamental backing.
  REJECT: Significant negative (fraud, SEBI notice, promoter selling, earnings miss) that may explain or reverse the breakout.
  No news at all → default WEAK (confidence 4).
"""

_RISK_SYSTEM = """You are a professional trading risk manager for an NSE systematic swing-trading
fund. Your job is to stress-test this setup from a capital-preservation perspective.

Think like a devil's advocate: assume the trade goes wrong. Is the risk/reward worth it?

Return ONLY a JSON object (no markdown, no prose):
{
  "verdict": "CONFIRM" | "WEAK" | "REJECT",
  "confidence": <integer 1-10>,
  "reasoning": "<2-3 sentences: risk/reward assessment, stop quality, tail risk, final verdict>",
  "bull_points": ["<manageable risk 1>", "<positive risk factor 2>"],
  "bear_points": ["<serious risk concern 1>"],
  "key_concern": "<highest-probability way this trade fails>"
}

Verdict guide for NSE swing trades (1-3 week horizon):
  CONFIRM: SL logical and < 6% away, R:R >= 1.5:1, Stage2, no extreme macro event risk.
  WEAK: SL valid but 6-8% away, OR market regime volatile, OR borderline stage, OR elevated timing risk.
  REJECT: SL illogical or > 8-10%, R:R < 1:1, illiquid (anomalous volume), OR extreme tail risk.
"""

_BULL_DEBATE_SYSTEM = """You are the BULL RESEARCHER in a structured investment debate.
Make the strongest possible case FOR entering this breakout trade.
Synthesize the most compelling bullish arguments from all three analysts.
Counter bear concerns where you can. Be specific — cite actual data points.
Respond in exactly 4-5 sentences. Plain text only — no JSON."""

_BEAR_DEBATE_SYSTEM = """You are the BEAR RESEARCHER in a structured investment debate.
Make the strongest possible case AGAINST entering this breakout trade.
Synthesize the most important bearish arguments and key risks.
Counter the bull thesis where you see genuine weakness. Be specific.
Respond in exactly 4-5 sentences. Plain text only — no JSON."""

_MODERATOR_SYSTEM = """You are the FUND MANAGER moderating a bull vs bear debate about an
NSE swing trade. You have heard both sides. Make a final, decisive trading call.

Return ONLY a JSON object:
{
  "final_verdict": "CONFIRM" | "WEAK" | "REJECT",
  "confidence": <integer 1-10>,
  "winner": "BULL" | "BEAR" | "DRAW",
  "reasoning": "<2-3 sentences: which argument was more convincing, final decision>"
}"""


# ── Prompt Builders ───────────────────────────────────────────────────────────

def _fmt(v, fmt=None, fallback="N/A"):
    if v is None:
        return fallback
    try:
        return fmt.format(v) if fmt else str(v)
    except Exception:
        return fallback


def _build_tech_prompt(sig: dict) -> str:
    close     = sig.get("close", 0) or 0
    ema20     = sig.get("ema20") or 0
    ema50     = sig.get("ema50") or 0
    ema200    = sig.get("ema200")
    atr14     = sig.get("atr14") or 0
    rsi       = sig.get("rsi") or 0
    vol_ratio = sig.get("vol_ratio") or 0
    high_52w  = sig.get("high_52w")
    macd_hist = sig.get("macd_hist")

    c_ema20   = f"{(close-ema20)/ema20*100:+.1f}%" if ema20 else "N/A"
    e20_e50   = f"{(ema20-ema50)/ema50*100:+.1f}%" if ema50 and ema20 else "N/A"
    c_ema200  = f"{(close-ema200)/ema200*100:+.1f}%" if ema200 else "N/A"
    atr_pct   = f"{atr14/close*100:.1f}%" if close else "N/A"
    near_52w  = f"{(high_52w-close)/high_52w*100:.1f}% below" if high_52w else "N/A"
    vol_flag  = "HIGH CONVICTION" if vol_ratio >= 2.0 else ("Moderate" if vol_ratio >= 1.5 else "LOW – watch carefully")
    rsi_flag  = ("APPROACHING OVERBOUGHT (scanner max=80)" if rsi > 75
                 else ("Strong momentum zone" if rsi >= 65
                 else ("Momentum zone" if rsi >= 55
                 else "Below momentum zone")))
    macd_desc = f"{macd_hist:.4f} ({'bullish crossover' if macd_hist and macd_hist > 0 else 'bearish'})" if macd_hist is not None else "N/A"

    # Supertrend direction (1=bullish, -1=bearish, None=N/A)
    st_dir = sig.get("supertrend_dir")
    if st_dir == 1:
        st_desc = "BULLISH (price above supertrend — uptrend confirmed)"
    elif st_dir == -1:
        st_desc = "BEARISH (price below supertrend — caution)"
    else:
        st_desc = "N/A"

    return f"""
NSE BREAKOUT SIGNAL – TECHNICAL ANALYSIS REQUEST
=================================================
Symbol      : {sig.get('symbol')}   |   Date: {sig.get('scan_date', 'today')}
Signal Type : {sig.get('signal_type', 'BREAKOUT')}
Close Price : ₹{close}
Stage       : {sig.get('stage')}
Rule Score  : {sig.get('score', 0)}/20  (min threshold 7; augmented: {sig.get('augmented_score', sig.get('score', 0))}/20)

── PRICE & TREND ──────────────────────────────
EMA20       : ₹{_fmt(ema20, '{:.2f}')}   (close vs EMA20: {c_ema20})
EMA50       : ₹{_fmt(ema50, '{:.2f}')}   (EMA20 vs EMA50: {e20_e50})
EMA200      : ₹{_fmt(ema200, '{:.2f}')}  (close vs EMA200: {c_ema200})
ATR14       : ₹{_fmt(atr14, '{:.2f}')}   ({atr_pct} of price – volatility)
Swing Low   : ₹{_fmt(sig.get('swing_low'), '{:.2f}')}

── MOMENTUM ───────────────────────────────────
RSI (14)    : {rsi:.1f}   >> {rsi_flag}
MACD Hist   : {macd_desc}
Supertrend  : {st_desc}

── VOLUME ─────────────────────────────────────
Vol Ratio   : {vol_ratio:.2f}x 20-day avg   >> {vol_flag}
52W High    : ₹{_fmt(high_52w, '{:.2f}')}  ({near_52w})

── ADVANCED PATTERNS ──────────────────────────
{sig.get('pattern_summary', 'Not computed.')}

── SCREENER REASONS ───────────────────────────
{sig.get('reasons', 'N/A')}

Perform your step-by-step technical analysis and return the JSON verdict.
""".strip()


def _build_sent_prompt(sig: dict, sentiment_report_text: str, news_headlines: str,
                       marketaux_text: str = "") -> str:
    # Conditionally include MarketAux section
    marketaux_section = ""
    if marketaux_text:
        marketaux_section = f"""

── MARKETAUX API SENTIMENT (entity-scored) ────
{marketaux_text}
"""

    return f"""
NSE BREAKOUT SIGNAL – SENTIMENT ANALYSIS REQUEST
=================================================
Symbol      : {sig.get('symbol')}   |   Date: {sig.get('scan_date', 'today')}
Close Price : ₹{sig.get('close')}
Signal Type : {sig.get('signal_type', 'BREAKOUT')}

── STRUCTURED SENTIMENT REPORT ────────────────
{sentiment_report_text}

── RAW RECENT NEWS ────────────────────────────
{news_headlines or 'No recent headlines found for this symbol.'}
{marketaux_section}── ANALYSIS CONTEXT ───────────────────────────
NSE India EQ stock. Consider: sector rotation, FII/DII flow impact,
RBI policy relevance, SEBI regulatory environment, promoter activity.
Breakout date: {sig.get('scan_date', 'today')}

Perform your sentiment chain-of-thought analysis and return the JSON verdict.
""".strip()


def _build_risk_prompt(sig: dict, open_count: int) -> str:
    close     = sig.get("close", 0) or 0
    atr14     = sig.get("atr14") or 0
    atr_pct   = f"{atr14/close*100:.1f}" if close else "N/A"
    swing_low = sig.get("swing_low") or 0
    rsi       = sig.get("rsi") or 0
    vol_ratio = sig.get("vol_ratio") or 0
    high_52w  = sig.get("high_52w")

    # Compute proposed SL and TP
    sl_atr   = round(close - ATR_SL_MULTIPLIER * atr14, 2) if atr14 > 0 else None
    sl_swing = round(swing_low * 0.99, 2) if swing_low else None
    candidates = [x for x in [sl_atr, sl_swing] if x and x < close]
    proposed_sl = max(candidates) if candidates else round(close * (1 - STOP_LOSS_PCT / 100), 2)
    risk_amount = close - proposed_sl
    proposed_tp = round(close + risk_amount * 2, 2)
    sl_dist_pct = round(risk_amount / close * 100, 1) if close else 0
    tp_dist_pct = round((proposed_tp - close) / close * 100, 1) if close else 0
    rr_ratio    = round(tp_dist_pct / sl_dist_pct, 1) if sl_dist_pct > 0 else 0
    near_52w_pct = round((high_52w - close) / high_52w * 100, 1) if high_52w else 0

    rsi_risk  = ("HIGH (near scanner ceiling 80)" if rsi > 76
                 else ("MEDIUM-HIGH" if rsi > 70
                 else ("MEDIUM" if rsi > 62 else "LOW")))
    liq_risk  = "STRONG" if vol_ratio >= 2.0 else ("ADEQUATE" if vol_ratio >= 1.5 else "WEAK — gap risk")
    pos_note  = f"{open_count}/{MAX_OPEN_POSITIONS}" if open_count >= 0 else "N/A"
    slots_free = max(0, MAX_OPEN_POSITIONS - (open_count or 0))

    return f"""
NSE BREAKOUT SIGNAL – RISK ANALYSIS REQUEST
=================================================
Symbol      : {sig.get('symbol')}   |   Date: {sig.get('scan_date', 'today')}
Stage       : {sig.get('stage')}
Signal Type : {sig.get('signal_type', 'BREAKOUT')}

── ENTRY PARAMETERS ───────────────────────────
Entry Price : ₹{close}
ATR14       : ₹{_fmt(atr14, '{:.2f}')}   ({atr_pct}% of price)
Swing Low   : ₹{_fmt(swing_low, '{:.2f}')}
Proposed SL : ₹{proposed_sl}   ({sl_dist_pct}% below entry)
Proposed TP : ₹{proposed_tp}   ({tp_dist_pct}% above entry)
Implied R:R : 1 : {rr_ratio}

── MARKET RISK INDICATORS ─────────────────────
RSI         : {rsi:.1f}   (overbought risk: {rsi_risk})
Vol Ratio   : {vol_ratio:.2f}x  (liquidity signal: {liq_risk})
Near 52W Hi : {near_52w_pct}% below peak

── ADVANCED PATTERNS ──────────────────────────
{sig.get('pattern_summary', 'Not computed.')}

── POSITION CONTEXT ───────────────────────────
Max Positions  : {MAX_OPEN_POSITIONS}
Current Open   : {pos_note}
Slots Free     : {slots_free}

Perform your risk chain-of-thought analysis and return the JSON verdict.
""".strip()


def _build_debate_context(sig: dict, verdicts: Dict[str, AgentVerdict]) -> str:
    def fmt_agent(name, v: AgentVerdict):
        bulls = "; ".join(v.bull_points[:2]) or "none stated"
        bears = "; ".join(v.bear_points[:2]) or "none stated"
        return (
            f"{name} Agent said {v.verdict} (confidence {v.confidence}/10)\n"
            f"  Reasoning: {v.reasoning}\n"
            f"  Bull points: {bulls}\n"
            f"  Bear points: {bears}\n"
            f"  Key concern: {v.key_concern}"
        )

    lines = [
        f"DEBATE CONTEXT – {sig.get('symbol')} @ ₹{sig.get('close')} | "
        f"Stage:{sig.get('stage')} | Score:{sig.get('score', 0)}/20",
        "",
    ]
    for name, v in verdicts.items():
        if not v.failed:
            lines.append(fmt_agent(name, v))
            lines.append("")
    return "\n".join(lines)


# ── LLM Call ──────────────────────────────────────────────────────────────────

def _call_llm(model: str, system_prompt: str, user_prompt: str,
              client, max_tokens: int = None) -> str:
    """
    Single OpenAI-compatible LLM call with exponential backoff for 429 rate-limit errors.
    Tries JSON mode first, falls back to plain text mode.
    Retries up to 4 times on rate-limit errors: waits 1s, 2s, 4s, 8s (capped at 30s).
    """
    if max_tokens is None:
        max_tokens = LLM_PANEL_MAX_TOKENS

    kwargs = dict(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        max_tokens=max_tokens,
        temperature=LLM_TEMPERATURE,
    )

    MAX_RETRIES = 4
    for retry in range(MAX_RETRIES):
        for attempt, use_json in enumerate([True, False]):
            if use_json:
                kwargs["response_format"] = {"type": "json_object"}
            else:
                kwargs.pop("response_format", None)
            try:
                resp = client.chat.completions.create(**kwargs)
                return resp.choices[0].message.content.strip()
            except Exception as e:
                err = str(e)
                # JSON mode not supported → drop it and retry immediately (no backoff)
                if attempt == 0 and ("response_format" in err.lower() or "json_object" in err.lower()):
                    continue
                # Rate limit (429) → exponential backoff then retry outer loop
                if "429" in err or "rate limit" in err.lower() or "rate_limit" in err.lower():
                    wait = min(2 ** retry, 30)  # 1s, 2s, 4s, 8s … capped at 30s
                    logger.warning(
                        f"[Panel] Rate limit on {model} (attempt {retry + 1}/{MAX_RETRIES}), "
                        f"waiting {wait}s…"
                    )
                    time.sleep(wait)
                    break  # break inner loop → go to next retry
                raise  # any other error → propagate immediately
        else:
            # Inner loop completed without break (no rate-limit hit) → success already returned
            break
    return ""


def _parse_agent_json(raw: str, agent_name: str) -> AgentVerdict:
    """Parse LLM JSON output into AgentVerdict. Tolerant of formatting issues."""
    text = raw
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to find a JSON object in the text
        start = text.find("{")
        end   = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start:end])
            except json.JSONDecodeError:
                return AgentVerdict(agent_name=agent_name, verdict="WEAK",
                                    confidence=5, reasoning=raw[:200], failed=True)
        else:
            return AgentVerdict(agent_name=agent_name, verdict="WEAK",
                                confidence=5, reasoning=raw[:200], failed=True)

    verdict = str(data.get("verdict", "WEAK")).upper()
    if verdict not in ("CONFIRM", "WEAK", "REJECT"):
        verdict = "WEAK"

    conf = int(data.get("confidence", 5))
    conf = max(1, min(10, conf))

    return AgentVerdict(
        agent_name=agent_name,
        verdict=verdict,
        confidence=conf,
        reasoning=str(data.get("reasoning", ""))[:400],
        bull_points=list(data.get("bull_points", []))[:3],
        bear_points=list(data.get("bear_points", []))[:3],
        key_concern=str(data.get("key_concern", ""))[:200],
        failed=False,
    )


def _call_agent(agent_name: str, model: str, system_prompt: str,
                user_prompt: str, client) -> AgentVerdict:
    """Wrapper: call LLM and parse result. Returns failed AgentVerdict on any exception."""
    try:
        raw = _call_llm(model, system_prompt, user_prompt, client)
        return _parse_agent_json(raw, agent_name)
    except Exception as e:
        logger.warning(f"[Panel] {agent_name} agent failed: {e}")
        return AgentVerdict(agent_name=agent_name, verdict="WEAK", confidence=4,
                            reasoning=f"Agent call failed: {str(e)[:120]}",
                            failed=True)


# ── Consensus Logic ───────────────────────────────────────────────────────────

def _compute_weighted_score(verdicts: Dict[str, AgentVerdict]) -> float:
    """
    Weighted consensus score (0.0 to 1.0).
    Each agent's contribution: weight × verdict_score × confidence_multiplier.
    """
    total = 0.0
    for name, v in verdicts.items():
        if v.failed:
            # Failed agent = pure neutral: no confidence multiplier (0.5 × weight)
            total += _AGENT_WEIGHTS.get(name, 0.33) * 0.5
            continue
        w       = _AGENT_WEIGHTS.get(name, 0.33)
        score   = _VERDICT_SCORE.get(v.verdict, 0.5)
        conf_m  = 0.50 + (v.confidence / 10.0) * 0.50   # 0.55 to 1.00 (wider range = harsher low-confidence penalty)
        total  += w * score * conf_m
    return round(total, 4)


def _should_trigger_debate(verdicts: Dict[str, AgentVerdict], score: float) -> bool:
    """
    Trigger debate when:
    1. TECHNICAL=CONFIRM AND SENTIMENT=REJECT (technical vs fundamental conflict)
    2. Any CONFIRM AND RISK=REJECT (risk manager veto)
    3. Score in grey zone [0.42, 0.65] (genuinely borderline — narrowed from 0.38-0.68)

    Do NOT trigger when only 1 agent is CONFIRM and others are WEAK (no real disagreement):
    e.g. TECH=CONFIRM, SENT=WEAK, RISK=WEAK → just output WEAK directly, save 3 LLM calls.
    """
    tech = verdicts.get("TECHNICAL")
    sent = verdicts.get("SENTIMENT")
    risk = verdicts.get("RISK")

    # Hard conflict: tech bullish, sentiment red flag
    if tech and sent and not tech.failed and not sent.failed:
        if tech.verdict == "CONFIRM" and sent.verdict == "REJECT":
            return True

    # Risk veto
    if risk and not risk.failed and risk.verdict == "REJECT":
        for name in ("TECHNICAL", "SENTIMENT"):
            v = verdicts.get(name)
            if v and not v.failed and v.verdict == "CONFIRM":
                return True

    # Grey zone — but skip if only 1 agent is CONFIRM and no agent is REJECT
    if _WEAK_THRESH <= score <= _CONFIRM_THRESH:
        active = [v for v in verdicts.values() if not v.failed]
        confirm_count = sum(1 for v in active if v.verdict == "CONFIRM")
        reject_count  = sum(1 for v in active if v.verdict == "REJECT")
        # Sole CONFIRM + all others WEAK = no genuine conflict → output WEAK without debate
        if confirm_count == 1 and reject_count == 0:
            return False
        return True

    return False


def _run_debate(sig: dict, verdicts: Dict[str, AgentVerdict],
                client) -> DebateResult:
    """
    3-turn sequential debate: Bull → Bear → Fund Manager (moderator).
    Sequential (not parallel) so each turn can reference prior arguments.

    Models:
      Bull + Bear (Turns 1-2): LLM_PANEL_RISK_MODEL  (llama-4-scout — fast, logic-focused)
      Moderator   (Turn 3):   LLM_PANEL_MODERATOR_MODEL (llama-4-maverick — final decision)
    """
    result = DebateResult(triggered=True)
    context = _build_debate_context(sig, verdicts)

    # Turn 1: Bull Researcher (Scout — argues FOR)
    try:
        bull_prompt = (
            f"{context}\n\n"
            f"BULL RESEARCHER – make your strongest case FOR this trade based on the evidence above."
        )
        result.bull_stance = _call_llm(
            LLM_PANEL_RISK_MODEL, _BULL_DEBATE_SYSTEM, bull_prompt,
            client, max_tokens=250
        )
    except Exception as e:
        result.bull_stance = f"Bull argument unavailable: {e}"

    # Turn 2: Bear Researcher (Scout — argues AGAINST)
    try:
        bear_prompt = (
            f"{context}\n\n"
            f"BULL argued:\n{result.bull_stance}\n\n"
            f"BEAR RESEARCHER – make your strongest case AGAINST this trade."
        )
        result.bear_stance = _call_llm(
            LLM_PANEL_RISK_MODEL, _BEAR_DEBATE_SYSTEM, bear_prompt,
            client, max_tokens=250
        )
    except Exception as e:
        result.bear_stance = f"Bear argument unavailable: {e}"

    # Turn 3: Fund Manager moderates (Maverick — reads all inputs, final CONFIRM/REJECT)
    try:
        mod_prompt = (
            f"{context}\n\n"
            f"BULL argued:\n{result.bull_stance}\n\n"
            f"BEAR argued:\n{result.bear_stance}\n\n"
            f"FUND MANAGER – review both arguments and give your final trading decision."
        )
        raw_mod = _call_llm(
            LLM_PANEL_MODERATOR_MODEL, _MODERATOR_SYSTEM, mod_prompt,
            client, max_tokens=350
        )
        # Parse moderator JSON
        mod = _parse_agent_json(raw_mod, "MODERATOR")
        # Extract final_verdict from raw if parse mapped to AgentVerdict
        try:
            data = json.loads(raw_mod.split("```")[-1].strip() if "```" in raw_mod else raw_mod)
            result.moderator_verdict   = str(data.get("final_verdict", mod.verdict)).upper()
            result.moderator_confidence = int(data.get("confidence", mod.confidence))
            result.moderator_reasoning  = str(data.get("reasoning", mod.reasoning))
            result.debate_winner        = str(data.get("winner", "DRAW")).upper()
        except Exception:
            result.moderator_verdict   = mod.verdict
            result.moderator_confidence = mod.confidence
            result.moderator_reasoning  = mod.reasoning
            result.debate_winner        = "DRAW"

        if result.moderator_verdict not in ("CONFIRM", "WEAK", "REJECT"):
            result.moderator_verdict = "WEAK"
        if result.debate_winner not in ("BULL", "BEAR", "DRAW"):
            result.debate_winner = "DRAW"
        result.moderator_confidence = max(1, min(10, result.moderator_confidence))

    except Exception as e:
        logger.warning(f"[Panel] Debate moderator failed: {e}")
        result.moderator_verdict = "WEAK"
        result.moderator_confidence = 4
        result.moderator_reasoning = f"Moderator call failed: {str(e)[:100]}"
        result.debate_winner = "DRAW"

    return result


def _build_final_verdict(
    verdicts: Dict[str, AgentVerdict],
    debate: DebateResult,
    weighted_score: float,
) -> tuple:
    """Returns (verdict, confidence, reasoning)."""
    if debate.triggered and debate.moderator_verdict in ("CONFIRM", "WEAK", "REJECT"):
        verdict = debate.moderator_verdict
        conf    = debate.moderator_confidence
        reason  = debate.moderator_reasoning
    else:
        if weighted_score >= _CONFIRM_THRESH:
            verdict = "CONFIRM"
        elif weighted_score >= _WEAK_THRESH:
            verdict = "WEAK"
        else:
            verdict = "REJECT"

        # Confidence: weighted average of all non-failed agents
        total_w = 0.0
        conf_w  = 0.0
        for name, v in verdicts.items():
            if not v.failed:
                w = _AGENT_WEIGHTS.get(name, 0.33)
                conf_w  += w * v.confidence
                total_w += w
        conf = round(conf_w / total_w) if total_w > 0 else 5
        conf = max(1, min(10, int(conf)))

        # Reasoning: pick the agent with highest confidence for the one-liner
        best = max(
            (v for v in verdicts.values() if not v.failed),
            key=lambda v: v.confidence,
            default=None,
        )
        if best:
            reason = f"[{best.agent_name}] {best.reasoning[:200]}"
        else:
            reason = f"Weighted score {weighted_score:.2f} → {verdict}"

    return verdict, conf, reason


# ── Main Panel Orchestrator ───────────────────────────────────────────────────

def run_panel(sig: dict, scan_date: str) -> Optional[PanelVerdict]:
    """
    Orchestrate the 3-agent panel for a single signal.

    Returns PanelVerdict, or None if a fatal error occurs (caller falls back to single LLM).
    """
    if not LLM_API_KEY:
        return None

    try:
        from openai import OpenAI as _OpenAI
        client = _OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL or None)
    except ImportError:
        logger.warning("[Panel] openai package not installed. Run: pip install openai")
        return None
    except Exception as e:
        logger.warning(f"[Panel] Could not create OpenAI client: {e}")
        return None

    # ── Pre-compute pattern data (no LLM) ─────────────────────────────────────
    patterns = {"pattern_summary": "Pattern analysis not available.",
                "pattern_bonus_score": 0, "vcp": None, "bull_flag": None}
    try:
        from data.database import load_ohlcv
        from analysis.technical import add_indicators
        from analysis.pattern_scanner import scan_advanced_patterns

        df = load_ohlcv(sig.get("symbol", ""))
        if not df.empty:
            df = add_indicators(df)
            patterns = scan_advanced_patterns(df)
    except Exception as e:
        logger.warning(f"[Panel] Pattern scan failed for {sig.get('symbol')}: {e}")

    sig["pattern_summary"]     = patterns["pattern_summary"]
    sig["augmented_score"]     = (sig.get("score") or 0) + patterns["pattern_bonus_score"]

    # ── Pre-compute sentiment report (no LLM) ─────────────────────────────────
    sentiment_text   = ""
    news_headlines   = ""
    try:
        from analysis.news_fetcher import get_full_news_for_symbol
        from analysis.sentiment_scorer import score_news_for_symbol

        news_items = get_full_news_for_symbol(sig.get("symbol", ""), limit=5)
        sent_report = score_news_for_symbol(sig.get("symbol", ""), news_items)
        sentiment_text  = sent_report.formatted_text
        news_headlines  = "\n".join(
            f"  [{i+1}] ({item.get('source','?')}) {item.get('title','')}"
            for i, item in enumerate(news_items[:5])
        ) or "No headlines."
    except Exception as e:
        logger.warning(f"[Panel] Sentiment pre-score failed for {sig.get('symbol')}: {e}")

    # ── MarketAux sentiment enrichment (optional, pluggable) ─────────────
    marketaux_text = ""
    try:
        from config import MARKETAUX_ENABLED
        if MARKETAUX_ENABLED:
            from analysis.marketaux_client import get_marketaux_sentiment, format_marketaux_for_prompt
            ma_report = get_marketaux_sentiment(sig.get("symbol", ""), scan_date)
            if ma_report:
                marketaux_text = format_marketaux_for_prompt(ma_report)
                if marketaux_text:
                    logger.info(f"[Panel] MarketAux enrichment for {sig.get('symbol')}: "
                                f"{ma_report.get('article_count', 0)} article(s), "
                                f"avg={ma_report.get('avg_sentiment', 0):.2f}")
    except Exception as e:
        logger.warning(f"[Panel] MarketAux enrichment failed for {sig.get('symbol')}: {e}")

    # Pull current open position count for risk prompt
    try:
        from data.database import get_open_positions
        open_count = len(get_open_positions())
    except Exception:
        open_count = 0

    # ── Build prompts ──────────────────────────────────────────────────────────
    tech_prompt = _build_tech_prompt(sig)
    sent_prompt = _build_sent_prompt(sig, sentiment_text, news_headlines, marketaux_text)
    risk_prompt = _build_risk_prompt(sig, open_count)

    # ── Run 3 agents IN PARALLEL ───────────────────────────────────────────────
    verdicts: Dict[str, AgentVerdict] = {}

    agent_tasks = [
        ("TECHNICAL", LLM_PANEL_TECH_MODEL, _TECH_SYSTEM, tech_prompt),
        ("SENTIMENT", LLM_PANEL_SENT_MODEL, _SENT_SYSTEM, sent_prompt),
        ("RISK",      LLM_PANEL_RISK_MODEL, _RISK_SYSTEM, risk_prompt),
    ]

    if PANEL_SEQUENTIAL_MODE:
        # Sequential mode: one agent at a time with a delay between calls.
        # Use when SENT+RISK share the same model to avoid competing for the same TPM bucket.
        for name, model, sys_p, usr_p in agent_tasks:
            verdicts[name] = _call_agent(name, model, sys_p, usr_p, client)
            if PANEL_AGENT_DELAY > 0:
                time.sleep(PANEL_AGENT_DELAY)
    else:
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(_call_agent, name, model, sys_p, usr_p, client): name
                for name, model, sys_p, usr_p in agent_tasks
            }
            for future in as_completed(futures, timeout=60):
                name = futures[future]
                try:
                    verdicts[name] = future.result()
                except Exception as e:
                    logger.warning(f"[Panel] {name} future failed: {e}")
                    verdicts[name] = AgentVerdict(agent_name=name, verdict="WEAK",
                                                  confidence=4, reasoning=str(e)[:100],
                                                  failed=True)

    # Ensure all three present (defensive)
    for name in ("TECHNICAL", "SENTIMENT", "RISK"):
        if name not in verdicts:
            verdicts[name] = AgentVerdict(agent_name=name, verdict="WEAK",
                                          confidence=4, reasoning="Agent missing",
                                          failed=True)

    # ── Compute weighted consensus ─────────────────────────────────────────────
    weighted_score = _compute_weighted_score(verdicts)

    # ── Debate if needed ───────────────────────────────────────────────────────
    debate = DebateResult(triggered=False)
    if _should_trigger_debate(verdicts, weighted_score):
        try:
            debate = _run_debate(sig, verdicts, client)
        except Exception as e:
            logger.warning(f"[Panel] Debate failed: {e}")
            debate = DebateResult(triggered=False)

    # ── Build final verdict ────────────────────────────────────────────────────
    final_verdict, final_conf, final_reason = _build_final_verdict(
        verdicts, debate, weighted_score
    )

    tech_v = verdicts.get("TECHNICAL", AgentVerdict("TECHNICAL", "WEAK", 5, ""))
    sent_v = verdicts.get("SENTIMENT", AgentVerdict("SENTIMENT", "WEAK", 5, ""))
    risk_v = verdicts.get("RISK",      AgentVerdict("RISK",      "WEAK", 5, ""))

    return PanelVerdict(
        llm_verdict=final_verdict,
        llm_confidence=final_conf,
        llm_reasoning=final_reason,
        tech_verdict=tech_v.verdict,
        tech_confidence=tech_v.confidence,
        tech_reasoning=tech_v.reasoning,
        sent_verdict=sent_v.verdict,
        sent_confidence=sent_v.confidence,
        sent_reasoning=sent_v.reasoning,
        risk_verdict=risk_v.verdict,
        risk_confidence=risk_v.confidence,
        risk_reasoning=risk_v.reasoning,
        debate_triggered=debate.triggered,
        debate_winner=debate.debate_winner if debate.triggered else "",
        debate_reasoning=debate.moderator_reasoning if debate.triggered else "",
        panel_method="MULTI_LLM",
        weighted_score=weighted_score,
        vcp_detected=1 if patterns.get("vcp") else 0,
        bull_flag_detected=1 if patterns.get("bull_flag") else 0,
        pattern_score=patterns.get("pattern_bonus_score", 0),
    )


# ── Enrichment cache staleness detection ──────────────────────────────────────

def _detect_new_enrichment_sources(scan_date: str, verdict_cache: dict) -> dict:
    """
    Check if new enrichment sources (MarketAux) are enabled but were
    NOT used when the cached panel verdicts were created.

    Returns a dict of {symbol: "reason"} for symbols whose cache should be
    invalidated so the panel re-runs with the new enrichment data.
    """
    stale: Dict[str, str] = {}
    if not verdict_cache:
        return stale

    try:
        from config import MARKETAUX_ENABLED
    except ImportError:
        return stale

    # Nothing new enabled — all cache entries are valid
    if not MARKETAUX_ENABLED:
        return stale

    import sqlite3
    from config import DB_PATH

    conn = sqlite3.connect(DB_PATH)
    cached_symbols = set(verdict_cache.keys())

    # Check MarketAux: if enabled, which cached symbols have no MarketAux data?
    ma_covered = set()
    if MARKETAUX_ENABLED:
        try:
            rows = conn.execute(
                "SELECT symbol FROM marketaux_cache WHERE scan_date = ?",
                (scan_date,)
            ).fetchall()
            ma_covered = {r[0] for r in rows}
        except Exception:
            pass  # table may not exist yet

    conn.close()

    # Mark symbols whose panel cache is stale
    for symbol in cached_symbols:
        reasons = []
        if MARKETAUX_ENABLED and symbol not in ma_covered:
            reasons.append("MarketAux")
        if reasons:
            stale[symbol] = "+".join(reasons)

    return stale


# ── Public API (drop-in replacement for validate_signals_batch) ───────────────

def validate_signals_panel(signals: list, scan_date: str) -> list:
    """
    Drop-in replacement for validate_signals_batch() in llm_validator.py.

    For each signal:
    1. Check panel verdict cache (skip if already validated today)
    2. Run 3-agent panel (or fall back to single LLM if panel fails)
    3. Merge PanelVerdict into sig dict (existing keys always populated)

    The existing display code reads sig["llm_verdict"], sig["llm_confidence"],
    sig["llm_reasoning"] — all always populated → zero changes needed downstream.
    """
    from data.database import get_panel_verdict_cache, save_breakout_log
    from analysis.llm_validator import validate_signal as single_llm_fallback
    from colorama import Fore, Style

    if not LLM_API_KEY:
        for sig in signals:
            sig["scan_date"]      = scan_date
            sig["llm_verdict"]    = "SKIPPED"
            sig["llm_confidence"] = None
            sig["llm_reasoning"]  = "LLM_API_KEY not set"
            sig["panel_method"]   = "SKIPPED"
        return signals

    verdict_cache = get_panel_verdict_cache(scan_date)
    total = len(signals)
    api_count    = 0
    cached_count = 0

    # ── Detect newly-enabled enrichment sources ──────────────────────────
    # If MarketAux was just enabled but the panel cache was created
    # without its data, we must invalidate the cache and re-run the panel
    # so the SENTIMENT agent gets the new data.
    _new_enrichment_sources = _detect_new_enrichment_sources(scan_date, verdict_cache)

    for i, sig in enumerate(signals, 1):
        sig["scan_date"] = scan_date
        symbol = sig.get("symbol", "?")

        # Cache hit — but invalidate if new enrichment sources are enabled
        if symbol in verdict_cache:
            if symbol in _new_enrichment_sources:
                # New enrichment source enabled → re-run panel with fresh data
                logger.info(f"[Panel] Cache invalidated for {symbol} — "
                            f"new enrichment: {_new_enrichment_sources[symbol]}")
            else:
                sig.update(verdict_cache[symbol])
                cached_count += 1
                verdict = sig.get("llm_verdict", "?")
                method  = sig.get("panel_method", "?")
                print(f"  [Panel {i:>3}/{total}] {symbol:<15} → {verdict} "
                      f"({method}, cached)", flush=True)
                continue

        # Cache miss — run panel
        print(f"  [Panel {i:>3}/{total}] {symbol:<15} ", end="", flush=True)

        try:
            panel = run_panel(sig, scan_date)
            if panel is None:
                raise ValueError("Panel returned None (no API key or import error)")

            sig.update(panel.to_dict())
            api_count += 1

        except Exception as e:
            # Fallback to single LLM
            logger.warning(f"[Panel] Failed for {symbol}: {e}. Falling back to single LLM.")
            try:
                single_llm_fallback(sig)
            except Exception as e2:
                sig["llm_verdict"]    = "SKIPPED"
                sig["llm_confidence"] = None
                sig["llm_reasoning"]  = str(e2)[:100]
            sig["panel_method"]   = "SINGLE_LLM"
            sig["weighted_score"] = 0.0
            api_count += 1

        verdict = sig.get("llm_verdict", "?")
        conf    = sig.get("llm_confidence")
        method  = sig.get("panel_method", "MULTI_LLM")
        conf_str = f"conf={conf}/10" if conf else ""

        # Colour output
        if verdict == "CONFIRM":
            v_col = Fore.GREEN
        elif verdict == "REJECT":
            v_col = Fore.RED
        elif verdict == "WEAK":
            v_col = Fore.YELLOW
        else:
            v_col = ""

        # Show per-agent breakdown if multi-LLM
        agent_str = ""
        if method == "MULTI_LLM":
            agent_str = (
                f" | TECH:{sig.get('tech_verdict','?')}({sig.get('tech_confidence','?')}) "
                f"SENT:{sig.get('sent_verdict','?')}({sig.get('sent_confidence','?')}) "
                f"RISK:{sig.get('risk_verdict','?')}({sig.get('risk_confidence','?')})"
            )
            if sig.get("debate_triggered"):
                agent_str += f" | DEBATE→{sig.get('debate_winner','?')}"

        print(f"→ {v_col}{verdict}{Style.RESET_ALL} {conf_str}{agent_str}")

    print(f"  [Panel] Done. API calls: {api_count} | Cached: {cached_count}")
    return signals
