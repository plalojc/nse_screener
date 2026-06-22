# ============================================================
# analysis/grok_validator.py - Grok batch validator
# ============================================================
from __future__ import annotations

import json
import re
import time
from typing import Any

import requests
from colorama import Fore, Style

from config import (
    GROK_VALIDATOR_BATCH_DELAY,
    GROK_VALIDATOR_BATCH_SIZE,
    GROK_VALIDATOR_MAX_RETRIES,
    GROK_VALIDATOR_MODEL,
    XAI_API_KEY,
)
from data.database import get_llm_verdict_cache


def _parse_json(text: str) -> dict[str, Any]:
    if not text:
        return {}
    cleaned = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if not match:
            return {}
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            return {}


def _safe_round(value, digits=2):
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _build_payload(batch: list[dict]) -> list[dict]:
    payload = []
    for sig in batch:
        payload.append({
            "symbol": sig.get("symbol"),
            "signal_type": sig.get("signal_type"),
            "price": _safe_round(sig.get("close")),
            "rsi": _safe_round(sig.get("rsi")),
            "vol_ratio": _safe_round(sig.get("vol_ratio")),
            "score": sig.get("score"),
            "swing_score": sig.get("swing_score"),
            "rs_rating": sig.get("rs_rating"),
            "stage": sig.get("stage"),
            "breakout_lookback": sig.get("breakout_lookback"),
            "turnover_cr": _safe_round(sig.get("turnover_cr")),
            "entry_risk_pct": _safe_round(sig.get("entry_risk_pct")),
            "ema20_extension_pct": _safe_round(sig.get("ema20_extension_pct")),
            "close_range_pos": _safe_round(sig.get("close_range_pos")),
            "ema20": _safe_round(sig.get("ema20")),
            "ema50": _safe_round(sig.get("ema50")),
            "ema200": _safe_round(sig.get("ema200")),
            "atr14": _safe_round(sig.get("atr14")),
            "swing_low": _safe_round(sig.get("swing_low")),
            "high_52w": _safe_round(sig.get("high_52w")),
            "macd_hist": _safe_round(sig.get("macd_hist"), 4),
            "supertrend_dir": sig.get("supertrend_dir"),
            "patterns": {
                "vcp": bool(sig.get("vcp_detected")),
                "bull_flag": bool(sig.get("bull_flag_detected")),
            },
            "catalyst": {
                "category": sig.get("catalyst_category"),
                "summary": sig.get("catalyst_summary"),
                "source": sig.get("catalyst_source"),
                "theme": sig.get("catalyst_theme"),
                "mapping_source": sig.get("catalyst_mapping_source"),
                "score": sig.get("catalyst_score"),
                "confidence": sig.get("catalyst_confidence"),
            },
            "scanner_reasons": sig.get("reasons", "")[:220],
        })
    return payload


def _build_prompt(batch: list[dict]) -> str:
    stock_data = _build_payload(batch)
    return f"""
You are a disciplined swing-trade analyst grading NSE India setups for a 2-4 week
hold. Judge every stock INDEPENDENTLY. Do not let one stock's news affect another.
Be SELECTIVE: a good screener confirms only the strongest minority of candidates.
As a rough guide, CONFIRM roughly the top 20-30%, WEAK the middle, REJECT the rest.
Quality over quantity - it is correct to reject most names on a weak day.

INPUT DATA (one object per stock):
{json.dumps(stock_data, indent=2)}

KEY FIELD - rs_rating (1-99): cross-sectional Relative Strength vs the whole NSE
universe scanned today. 99 = strongest price momentum, 50 = median, low = laggard.
This is a leadership signal: prefer leaders, be skeptical of breakouts in laggards.

For EACH stock, evaluate:
1. Leadership / relative strength:
   - rs_rating >= 80 is a true leader (favourable). 60-80 is acceptable.
   - rs_rating < 50 is a market laggard: a breakout here is lower quality - lean WEAK/REJECT
     unless a strong, specific catalyst justifies it.
2. Technical quality:
   - Stage2 preferred; penalize Stage3 parabolic/overextended moves.
   - STAGE1 = pre-breakout/watchlist base, NOT a confirmed breakout. Want tight
     compression, near-breakout positioning, improving volume, ideally a catalyst.
   - WATCHLIST = lower-priority fill; CONFIRM only means "monitor closely".
   - NEWS = catalyst-driven; confirm the company is a real beneficiary.
   - Prior 55-day breakouts beat weaker 20-day breakouts for a 2-4 week swing.
   - Healthy RSI ~55-75; above 80 is overextended.
   - Volume strong above 1.8x, weak below 1.5x.
   - Not too extended: entries >10% above EMA20 are risky; fresh breaks near the
     trigger are higher quality than ones that already ran.
   - Entry risk near/under 6% preferred; wide stops make a 2R target harder.
   - Close above EMA200 is a positive macro-trend filter.
3. Catalyst (assess, do NOT browse):
   - You do NOT have live web access in this call. Judge the catalyst ONLY from the
     provided 'catalyst' fields plus durable knowledge. Do NOT fabricate or assume
     recent news that is not given. Live web/X verification is handled by a
     separate downstream layer.
   - If the provided catalyst is empty or unconvincing, set catalyst=null and judge
     mostly from technicals + relative strength.
4. Red flags (any serious one => normally REJECT):
   - SEBI/regulatory probe, fraud, pledge/promoter selling, auditor resignation,
     court action, major downgrade, severe earnings miss, order cancellation.
5. Liquidity/tradability:
   - Be cautious with low-price/illiquid names where a volume spike may be noise.
   - Prefer clean institutional participation over one-off speculative spikes.
6. Risk/reward:
   - Is the ATR/swing-low stop logical and a 2R target realistic within 2-4 weeks?
   - Penalize setups already far above moving averages.
7. Instrument validity:
   - Reject ETFs, bonds, SGBs, mutual funds, index funds, warrants, rights, and
     any non-equity instrument.

CONFIDENCE SCALE (integer 0-10) - calibrate, do not default to the middle:
   9-10 = textbook leader, clean setup, low risk, real edge
   7-8  = strong, minor caveat
   5-6  = mixed / borderline (usually WEAK)
   2-4  = weak setup or notable concern
   0-1  = clear reject / invalid
Confidence must agree with the verdict (CONFIRM>=7, WEAK 4-6, REJECT<=3).

Return ONLY valid JSON matching this exact schema:
{{
  "evaluations": [
    {{
      "symbol": "TICKER",
      "verdict": "CONFIRM" | "WEAK" | "REJECT",
      "confidence": 8,
      "reasoning": "One concise sentence with the main reason, citing RS/leadership when relevant.",
      "catalyst": "Specific catalyst from input, or null",
      "risk": "Main risk, or null",
      "is_valid_equity": true
    }}
  ]
}}

Rules:
- The evaluations array MUST contain exactly {len(batch)} items, one per input symbol.
- Do not skip any stock, do not add extra symbols, use the exact input symbol strings.
- CONFIRM: valid equity, leader or strong RS, clean technical setup, no major red
  flags, and either a credible catalyst or exceptional price/volume confirmation.
- WEAK: valid but missing catalyst, laggard RS, borderline RSI/volume/stage,
  uncertain liquidity, or stretched/extended entry.
- REJECT: invalid/non-equity, serious negative news, poor liquidity, parabolic or
  overextended move, weak technicals, clear laggard, or misleading volume spike.
- For STAGE1, CONFIRM means "strong watchlist candidate", not breakout confirmation.
- For WATCHLIST, be stricter: CONFIRM only when RS + technicals are unusually strong.
- For NEWS, name the catalyst category in reasoning; reject stale/immaterial/negative items.
- When genuinely uncertain, prefer WEAK over CONFIRM.
""".strip()


def _normalise_verdict(value: Any) -> str:
    verdict = str(value or "WEAK").upper().strip()
    return verdict if verdict in {"CONFIRM", "WEAK", "REJECT", "SKIPPED"} else "WEAK"


def _normalise_confidence(value: Any) -> int:
    try:
        return max(0, min(10, int(value)))
    except (TypeError, ValueError):
        return 5


def _apply_failure(batch: list[dict], reason: str):
    for sig in batch:
        sig["llm_verdict"] = "SKIPPED"
        sig["llm_confidence"] = 0
        sig["llm_reasoning"] = reason[:500]
        sig["panel_method"] = "GROK_BATCH"
        sig["llm_model"] = GROK_VALIDATOR_MODEL


def _print_result(prefix: str, symbol: str, verdict: str, confidence: int | None):
    conf_str = f" ({confidence}/10)" if confidence is not None else ""
    if verdict == "CONFIRM":
        label = Fore.GREEN + verdict + conf_str + Style.RESET_ALL
    elif verdict == "REJECT":
        label = Fore.RED + verdict + conf_str + Style.RESET_ALL
    elif verdict == "WEAK":
        label = Fore.YELLOW + verdict + conf_str + Style.RESET_ALL
    else:
        label = verdict + conf_str
    print(f"  [{prefix}] {symbol:<15} -> {label}")


def validate_signals_grok_batch(signals: list, scan_date: str, batch_size: int | None = None) -> list:
    """
    Validate signals with Grok in compact batches through xAI's OpenAI-compatible API.
    Updates each signal in-place with llm_verdict, llm_confidence, and llm_reasoning.
    """
    if not XAI_API_KEY:
        print(Fore.RED + "\n[4/5] Grok validation SKIPPED.")
        print(Fore.RED + "      Reason: XAI_API_KEY is not set.")
        for sig in signals:
            sig["scan_date"] = scan_date
            sig["llm_verdict"] = "SKIPPED"
            sig["llm_confidence"] = 0
            sig["llm_reasoning"] = "XAI_API_KEY not set"
            sig["panel_method"] = "SKIPPED"
            sig["llm_model"] = GROK_VALIDATOR_MODEL
        return signals

    batch_size = batch_size or GROK_VALIDATOR_BATCH_SIZE

    verdict_cache = get_llm_verdict_cache(
        scan_date,
        panel_method="GROK_BATCH",
        llm_model=GROK_VALIDATOR_MODEL,
    )
    to_api = []
    cache_count = 0
    for sig in signals:
        sig["scan_date"] = scan_date
        symbol = sig.get("symbol", "")
        if symbol in verdict_cache:
            sig.update(verdict_cache[symbol])
            sig.setdefault("panel_method", "GROK_BATCH")
            cache_count += 1
            _print_result("Grok cached", symbol, sig.get("llm_verdict", "?"), sig.get("llm_confidence"))
        else:
            to_api.append(sig)

    print(
        f"  [Grok] Validating {len(to_api)} signal(s) in batches of {batch_size} "
        f"with model={GROK_VALIDATOR_MODEL}"
    )

    api_batches = 0
    total_batches = (len(to_api) + batch_size - 1) // batch_size if to_api else 0
    for start in range(0, len(to_api), batch_size):
        batch = to_api[start:start + batch_size]
        prompt = _build_prompt(batch)
        delay = 2.0

        for attempt in range(GROK_VALIDATOR_MAX_RETRIES):
            try:
                api_batches += 1 if attempt == 0 else 0
                print(f"  [Grok] Evaluating batch {start // batch_size + 1} of {total_batches} ({len(batch)} stock(s))...")
                response = requests.post(
                    "https://api.x.ai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {XAI_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": GROK_VALIDATOR_MODEL,
                        "messages": [
                            {"role": "system", "content": "You are a quantitative analyst. Output exact JSON only."},
                            {"role": "user", "content": prompt},
                        ],
                        "response_format": {"type": "json_object"},
                    },
                    timeout=180,
                )
                response.raise_for_status()
                payload = response.json()
                content = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
                parsed = _parse_json(content or "")
                evaluations = parsed.get("evaluations", [])
                eval_map = {
                    str(item.get("symbol", "")).upper().strip(): item
                    for item in evaluations
                    if isinstance(item, dict)
                }

                for sig in batch:
                    symbol = str(sig.get("symbol", "")).upper().strip()
                    item = eval_map.get(symbol)
                    if item:
                        verdict = _normalise_verdict(item.get("verdict"))
                        confidence = _normalise_confidence(item.get("confidence"))
                        reasoning = str(item.get("reasoning") or "No reason provided.")
                        catalyst = item.get("catalyst")
                        risk = item.get("risk")
                        if item.get("is_valid_equity") is False:
                            verdict = "REJECT"
                            if "non-equity" not in reasoning.lower():
                                reasoning = f"{reasoning} Instrument appears to be non-equity."
                        extras = []
                        if catalyst:
                            extras.append(f"Catalyst: {catalyst}")
                        if risk:
                            extras.append(f"Risk: {risk}")
                        if extras:
                            reasoning = f"{reasoning} | " + " | ".join(extras)
                    else:
                        verdict = "SKIPPED"
                        confidence = 0
                        reasoning = "Grok did not return an evaluation for this symbol."

                    sig["llm_verdict"] = verdict
                    sig["llm_confidence"] = confidence
                    sig["llm_reasoning"] = reasoning[:500]
                    sig["panel_method"] = "GROK_BATCH"
                    sig["llm_model"] = GROK_VALIDATOR_MODEL
                    _print_result("Grok", sig.get("symbol", ""), verdict, confidence)

                break
            except Exception as exc:
                print(Fore.YELLOW + f"  [WARN] Grok batch error: {exc}")
                if attempt < GROK_VALIDATOR_MAX_RETRIES - 1:
                    time.sleep(delay)
                    delay *= 2
                else:
                    _apply_failure(batch, f"Grok batch API failure: {exc}")

        if GROK_VALIDATOR_BATCH_DELAY > 0:
            time.sleep(GROK_VALIDATOR_BATCH_DELAY)

    print(f"\n  Grok: {api_batches} API batch call(s), {cache_count} from cache.")
    return signals
