
# ============================================================
# analysis/live_validator.py – Gemini + Google Search Grounding
# ============================================================
# 2nd-pass live validation for breakout signals.
# Uses Gemini with Google Search to check real-time news before
# confirming or overriding the Groq panel verdict.
#
# FREE: 500 grounded searches/day on Gemini Flash.
# Get API key: https://aistudio.google.com/apikey
#
# Requires: pip install google-genai
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
# Panel Verdict | Gemini Verdict | Final Result
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


# ── Gemini API Call ─────────────────────────────────────────────────────────────

_SYSTEM_INSTRUCTION = (
    "You are a senior equity research analyst specialising in NSE India stocks. "
    "You have access to Google Search. Always search for the latest news about "
    "the stock before making your assessment. Be factual, cite sources, and "
    "return ONLY valid JSON in your response."
)


def _call_gemini_with_search(prompt: str) -> dict:
    """
    Call Gemini with Google Search grounding enabled.
    Returns parsed dict: {verdict, confidence, reasoning, live_catalysts, live_risks}
    or None on failure.
    """
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        logger.warning(
            "[Live] google-genai package not installed. "
            "Run: pip install google-genai"
        )
        return None

    if not LIVE_API_KEY:
        return None

    try:
        client = genai.Client(api_key=LIVE_API_KEY)

        # Enable Google Search grounding
        google_search_tool = types.Tool(
            google_search=types.GoogleSearch()
        )

        response = client.models.generate_content(
            model=LIVE_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[google_search_tool],
                system_instruction=_SYSTEM_INSTRUCTION,
                max_output_tokens=512,
                temperature=0.3,
            ),
        )

        # Extract text response
        raw_text = response.text.strip() if response.text else ""

        # Extract grounding metadata (search sources)
        sources = []
        try:
            gm = response.candidates[0].grounding_metadata
            if gm and gm.grounding_chunks:
                for chunk in gm.grounding_chunks:
                    if hasattr(chunk, "web") and chunk.web:
                        sources.append({
                            "title": getattr(chunk.web, "title", ""),
                            "uri":   getattr(chunk.web, "uri", ""),
                        })
        except Exception:
            pass  # grounding metadata may not always be present

        # Parse JSON from response
        parsed = _parse_live_json(raw_text)
        if parsed:
            parsed["_sources"] = sources[:5]  # keep top 5 sources
        return parsed

    except Exception as e:
        logger.warning(f"[Live] Gemini call failed: {e}")
        return None


def _parse_live_json(raw: str) -> dict:
    """Parse Gemini response JSON, handling markdown fences and edge cases."""
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
    Validate a single signal using Gemini + Google Search grounding.

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

    result = _call_gemini_with_search(prompt)

    if result is None:
        return {
            "live_verdict":    "SKIPPED",
            "live_confidence": None,
            "live_reasoning":  "Gemini call failed or unavailable",
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
    Validate a list of signals using Gemini + Google Search grounding.
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

    for idx, sig in enumerate(signals, 1):
        symbol = sig.get("symbol", "?")
        panel_verdict = sig.get("llm_verdict", "SKIPPED")

        # Only validate CONFIRM and WEAK (skip REJECTs)
        if panel_verdict not in ("CONFIRM", "WEAK"):
            sig["live_verdict"]    = "SKIPPED"
            sig["live_confidence"] = None
            sig["live_reasoning"]  = "Panel verdict was REJECT/SKIPPED"
            continue

        # Call Gemini with Google Search
        result = validate_with_live_search(sig)

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

        # Small delay between API calls to avoid rate limits
        if idx < total:
            time.sleep(0.5)

    # Summary
    override_str = f"Overrides: {', '.join(overrides)}" if overrides else "No overrides"
    print(
        f"  [Live] Done. {total} signal(s) validated. {override_str}"
    )
