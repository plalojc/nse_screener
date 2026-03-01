
# ============================================================
# analysis/live_validator.py – Claude + Web Search Validation
# ============================================================
# 2nd-pass live validation for breakout signals.
# Uses Claude Opus 4.6 with server-side web_search tool to check
# real-time news before confirming or overriding the Groq panel verdict.
#
# Model: claude-opus-4-6 (default)
#   - Server-side web search: $10 per 1,000 searches
#   - Claude searches the web automatically, cites sources
#   - max_uses=3 per signal (limits search count per call)
#
# Rate-limit: Anthropic SDK auto-retries 429s (2x default)
#             + custom exponential backoff (4s→8s→16s→32s)
# Cache: same-day re-runs skip API calls (uses DB cache)
#
# API key: https://console.anthropic.com/settings/keys
# Requires: pip install anthropic
# ============================================================

import json
import re
import logging
import time

from config import (
    LIVE_API_KEY, LIVE_MODEL, LIVE_PROMPT_TEMPLATE, USE_LIVE_VALIDATION,
)
from data.database import save_breakout_log

logger = logging.getLogger(__name__)


# ── Override Logic ──────────────────────────────────────────────────────────────
# Panel Verdict | Live Verdict   | Final Result
# ─────────────────────────────────────────────
# CONFIRM       | CONFIRM        | CONFIRM   (double confirmed)
# CONFIRM       | WEAK           | WEAK      (live data lacks conviction)
# CONFIRM       | REJECT         | WEAK      (red flag found, downgrade)
# WEAK          | CONFIRM        | CONFIRM   (live data upgrades)
# WEAK          | WEAK           | WEAK      (no change)
# WEAK          | REJECT         | REJECT    (both negative)

_OVERRIDE_TABLE = {
    ("CONFIRM", "CONFIRM"): "CONFIRM",
    ("CONFIRM", "WEAK"):    "WEAK",
    ("CONFIRM", "REJECT"):  "WEAK",
    ("WEAK",    "CONFIRM"): "CONFIRM",
    ("WEAK",    "WEAK"):    "WEAK",
    ("WEAK",    "REJECT"):  "REJECT",
}


def _apply_override(panel_verdict: str, live_verdict: str) -> str:
    """Return final verdict after combining panel + live verdicts."""
    return _OVERRIDE_TABLE.get(
        (panel_verdict.upper(), live_verdict.upper()),
        panel_verdict,  # fallback: keep panel verdict if combo not in table
    )


# ── Claude + Web Search API Call ──────────────────────────────────────────────

_SYSTEM_INSTRUCTION = (
    "You are a senior equity research analyst specialising in NSE India stocks. "
    "You have access to a web search tool. Always search for the latest news about "
    "the stock before making your assessment. Be factual, cite sources, and "
    "return ONLY valid JSON in your final response."
)


def _call_claude_with_search(prompt: str) -> dict:
    """
    Call Claude with server-side web_search tool enabled.
    Claude automatically searches the web and returns results with citations.
    Returns parsed dict: {verdict, confidence, reasoning, live_catalysts, live_risks}
    or None on failure.
    """
    try:
        import anthropic
    except ImportError:
        logger.warning(
            "[Live] anthropic package not installed. "
            "Run: pip install anthropic"
        )
        return None

    if not LIVE_API_KEY:
        logger.warning("[Live] LIVE_API_KEY not set.")
        return None

    client = anthropic.Anthropic(api_key=LIVE_API_KEY)

    MAX_RETRIES = 4
    for retry in range(MAX_RETRIES):
        try:
            response = client.messages.create(
                model=LIVE_MODEL,
                max_tokens=1024,
                system=_SYSTEM_INSTRUCTION,
                messages=[{"role": "user", "content": prompt}],
                tools=[{
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": 3,
                    "user_location": {
                        "type": "approximate",
                        "country": "IN",
                        "timezone": "Asia/Kolkata",
                    },
                }],
            )

            # Handle pause_turn: if Claude paused mid-turn, continue
            if response.stop_reason == "pause_turn":
                logger.info("[Live] Claude paused turn, continuing...")
                # Send response back to let Claude finish
                response = client.messages.create(
                    model=LIVE_MODEL,
                    max_tokens=1024,
                    system=_SYSTEM_INSTRUCTION,
                    messages=[
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": response.content},
                    ],
                    tools=[{
                        "type": "web_search_20250305",
                        "name": "web_search",
                        "max_uses": 3,
                        "user_location": {
                            "type": "approximate",
                            "country": "IN",
                            "timezone": "Asia/Kolkata",
                        },
                    }],
                )

            # Extract text from response content blocks
            raw_text = ""
            sources = []
            for block in response.content:
                if hasattr(block, "type"):
                    if block.type == "text":
                        raw_text += block.text
                        # Extract citations if present
                        if hasattr(block, "citations") and block.citations:
                            for citation in block.citations:
                                if hasattr(citation, "url"):
                                    sources.append({
                                        "title": getattr(citation, "title", ""),
                                        "uri":   getattr(citation, "url", ""),
                                    })

            raw_text = raw_text.strip()

            # Parse JSON from response
            parsed = _parse_live_json(raw_text)
            if parsed:
                # Deduplicate sources by URL
                seen = set()
                unique_sources = []
                for s in sources:
                    if s["uri"] not in seen:
                        seen.add(s["uri"])
                        unique_sources.append(s)
                parsed["_sources"] = unique_sources[:5]
            return parsed

        except Exception as e:
            err_str = str(e)
            # Check for rate limit or server errors
            is_rate_limit = (
                "429" in err_str or
                "rate_limit" in err_str.lower() or
                "rate limit" in err_str.lower() or
                "overloaded" in err_str.lower()
            )
            is_server_error = "500" in err_str or "529" in err_str
            if is_rate_limit or is_server_error:
                wait = min(4 * (2 ** retry), 60)  # 4s, 8s, 16s, 32s
                logger.warning(
                    f"[Live] Claude {'rate limit' if is_rate_limit else 'server error'} "
                    f"(attempt {retry + 1}/{MAX_RETRIES}), waiting {wait}s\u2026"
                )
                time.sleep(wait)
                continue
            # Non-retryable error — log and give up
            logger.warning(f"[Live] Claude call failed: {e}")
            return None

    # All retries exhausted
    logger.warning(f"[Live] Claude API errors persist after {MAX_RETRIES} retries, skipping.")
    return None


def _parse_live_json(raw: str) -> dict:
    """Parse Claude response JSON, handling markdown fences and edge cases."""
    if not raw:
        return None

    # Strip markdown code fences
    if "```" in raw:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
        if match:
            raw = match.group(1).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Try to extract JSON object from text
        match = re.search(r"\{[\s\S]*\}", raw)
        if match:
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                logger.warning(f"[Live] Could not parse JSON from response")
                return None
        else:
            return None

    verdict = str(data.get("verdict", "WEAK")).upper()
    if verdict not in ("CONFIRM", "WEAK", "REJECT"):
        verdict = "WEAK"

    confidence = data.get("confidence", 5)
    try:
        confidence = max(1, min(10, int(confidence)))
    except (TypeError, ValueError):
        confidence = 5

    return {
        "verdict":        verdict,
        "confidence":     confidence,
        "reasoning":      str(data.get("reasoning", ""))[:300],
        "live_catalysts": data.get("live_catalysts", []),
        "live_risks":     data.get("live_risks", []),
    }


# ── Single Signal Validation ───────────────────────────────────────────────────

def validate_with_live_search(sig: dict) -> dict:
    """
    Validate a single signal using Claude + web search.

    Args:
        sig: Signal dict with keys like symbol, close, signal_type, etc.

    Returns:
        dict with live_verdict, live_confidence, live_reasoning, _sources
        or a SKIPPED result on failure.
    """
    prompt = LIVE_PROMPT_TEMPLATE.format(
        symbol=sig.get("symbol", "?"),
        close=sig.get("close", 0),
        signal_type=sig.get("signal_type", "BREAKOUT"),
        stage=sig.get("stage", "?"),
        score=sig.get("score", 0),
        rsi=round(sig.get("rsi", 0), 1),
        vol_ratio=round(sig.get("vol_ratio", 0), 1),
        panel_verdict=sig.get("llm_verdict", "SKIPPED"),
        panel_reasoning=sig.get("llm_reasoning", "N/A"),
    )

    result = _call_claude_with_search(prompt)

    if result is None:
        return {
            "live_verdict":    "SKIPPED",
            "live_confidence": None,
            "live_reasoning":  "Claude call failed or unavailable",
            "_sources":        [],
        }

    return {
        "live_verdict":    result["verdict"],
        "live_confidence": result["confidence"],
        "live_reasoning":  result["reasoning"],
        "_sources":        result.get("_sources", []),
        "_catalysts":      result.get("live_catalysts", []),
        "_risks":          result.get("live_risks", []),
    }


# ── Batch Validation (public API) ──────────────────────────────────────────────

def validate_signals_live(signals: list, scan_date: str):
    """
    Validate a list of signals using Claude + web search.
    Only processes CONFIRM/WEAK signals (REJECTs are skipped to save quota).

    Mutates each signal dict in-place:
      - sig["live_verdict"]    = CONFIRM / WEAK / REJECT / SKIPPED
      - sig["live_confidence"] = 1-10
      - sig["live_reasoning"]  = string citing live sources
      - sig["llm_verdict"]     = may be overridden by live result

    Also persists live fields to breakout_log via save_breakout_log().
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
            sig["live_verdict"]    = "SKIPPED"
            sig["live_confidence"] = None
            sig["live_reasoning"]  = "Panel verdict was REJECT/SKIPPED"
            continue

        # Cache hit — already live-validated today (loaded from breakout_log by panel cache)
        existing_live = sig.get("live_verdict")
        if existing_live and existing_live not in ("SKIPPED", "", None):
            cached_count += 1
            if existing_live == "CONFIRM":
                v_color = Fore.GREEN
            elif existing_live == "REJECT":
                v_color = Fore.RED
            else:
                v_color = Fore.YELLOW
            print(
                f"  [Live {idx}/{total}] {symbol:<15} -> "
                f"{v_color}{existing_live:<7}{Style.RESET_ALL} (cached)"
            )
            continue

        # Cache miss — call Claude with web search
        result = validate_with_live_search(sig)
        api_count += 1

        sig["live_verdict"]    = result["live_verdict"]
        sig["live_confidence"] = result["live_confidence"]
        sig["live_reasoning"]  = result["live_reasoning"]

        # Apply override logic
        live_v = result["live_verdict"]
        if live_v != "SKIPPED":
            original = panel_verdict
            final = _apply_override(panel_verdict, live_v)

            # Override the main verdict if changed
            if final != original:
                sig["llm_verdict"] = final
                overrides.append(f"{original}->{final}")

            # Color the output
            if live_v == "CONFIRM":
                v_color = Fore.GREEN
            elif live_v == "REJECT":
                v_color = Fore.RED
            else:
                v_color = Fore.YELLOW

            conf_str = f"conf={result['live_confidence']}/10" if result['live_confidence'] else ""
            reason_short = result["live_reasoning"][:60] if result["live_reasoning"] else ""

            print(
                f"  [Live {idx}/{total}] {symbol:<15} -> "
                f"{v_color}{live_v:<7}{Style.RESET_ALL} "
                f"{conf_str} ({reason_short})"
            )
        else:
            print(f"  [Live {idx}/{total}] {symbol:<15} -> SKIPPED")

        # Persist to DB
        save_breakout_log(scan_date, sig)

        # Small delay between API calls
        if idx < total:
            time.sleep(1.0)

    # Summary
    override_str = f"Overrides: {', '.join(overrides)}" if overrides else "No overrides"
    print(
        f"  [Live] Done. API calls: {api_count} | Cached: {cached_count} | {override_str}"
    )
