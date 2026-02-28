
# ============================================================
# analysis/llm_validator.py – LLM-based signal validation
# ============================================================
#
# Recommended LLMs for this task (fast, cheap, strong JSON output):
#
#  ┌──────────────────────────────────────────────────────────┐
#  │ Provider  │ Model                 │ Why best here        │
#  ├──────────────────────────────────────────────────────────┤
#  │ Groq      │ llama-3.3-70b-versatile│ FREE, ~300 tok/s,   │
#  │           │                       │ excellent reasoning  │
#  ├──────────────────────────────────────────────────────────┤
#  │ Google    │ gemini-2.0-flash      │ Free tier (generous) │
#  │ Gemini    │                       │ 1M context, fast     │
#  ├──────────────────────────────────────────────────────────┤
#  │ OpenAI    │ gpt-4o-mini           │ Cheap ($0.15/M tkn), │
#  │           │                       │ reliable JSON mode   │
#  ├──────────────────────────────────────────────────────────┤
#  │ OpenRouter│ any of the above      │ Single API key for   │
#  │           │                       │ all providers        │
#  └──────────────────────────────────────────────────────────┘
#
#  DEFAULT: Groq (free) — set GROQ_API_KEY in .env or environment.
#  To switch providers update LLM_PROVIDER in config.py.
# ============================================================

import json
import logging
import sys
from config import (
    LLM_PROVIDER, LLM_MODEL, LLM_API_KEY, LLM_BASE_URL,
    LLM_MAX_TOKENS, LLM_TEMPERATURE,
)

# Ensure LLM warnings always appear on the terminal even without basicConfig
logger = logging.getLogger(__name__)
if not logger.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setLevel(logging.WARNING)
    logger.addHandler(_h)
    logger.setLevel(logging.WARNING)

# ── System prompt ─────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """You are a quantitative equity analyst specialising in NSE (India) 
breakout trading. You will receive a technical signal detected by a rule-based screener.
Your job is to validate the signal and return ONLY a JSON object — no markdown, no prose.

Return exactly:
{
  "verdict":    "CONFIRM" | "WEAK" | "REJECT",
  "confidence": <integer 1-10>,
  "reasoning":  "<one concise sentence>"
}

Verdict guide:
  CONFIRM   – Multiple strong confluences; high-probability setup.
  WEAK      – Setup exists but one or more concerns (RSI too high, low vol, late entry, etc.)
  REJECT    – Setup is flawed, overbought, or low conviction.
"""

# ── Signal → prompt ───────────────────────────────────────────────────────────

def _build_user_prompt(sig: dict) -> str:
    raw_news = sig.get("news") or []
    news_titles = (
        "; ".join(
            item["title"] if isinstance(item, dict) else str(item)
            for item in raw_news[:3]
        ) or "None"
    )
    return f"""
NSE BREAKOUT SIGNAL – VALIDATION REQUEST
=========================================
Symbol       : {sig.get('symbol')}
Date         : {sig.get('scan_date', 'today')}
Signal type  : {sig.get('signal_type', 'BREAKOUT')}
Close price  : ₹{sig.get('close')}
Stage        : {sig.get('stage')}
Score        : {sig.get('score')} / 20

Technical indicators:
  RSI (14)   : {sig.get('rsi')}
  Volume ratio: {sig.get('vol_ratio')}x (vs 20-day avg)
  EMA20      : ₹{sig.get('ema20')}
  EMA50      : ₹{sig.get('ema50')}
  ATR14      : ₹{sig.get('atr14')}
  Swing low  : ₹{sig.get('swing_low')}

Screener reasons:
  {sig.get('reasons')}

Recent news headlines (if any):
  {news_titles}

Respond with the JSON object only.
""".strip()


# ── LLM call ──────────────────────────────────────────────────────────────────

def _call_openai_compat(user_prompt: str) -> dict:
    """Works with OpenAI, Groq, OpenRouter (all OpenAI-compatible)."""
    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("[LLM] openai package not installed. Run: pip install openai")
        return _skipped("openai package missing")

    if not LLM_API_KEY:
        logger.warning("[LLM] No API key configured (LLM_API_KEY). Skipping validation.")
        return _skipped("no API key")

    client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL or None)

    kwargs = dict(
        model=LLM_MODEL,
        messages=[
            {"role": "system",  "content": _SYSTEM_PROMPT},
            {"role": "user",    "content": user_prompt},
        ],
        max_tokens=LLM_MAX_TOKENS,
        temperature=LLM_TEMPERATURE,
    )

    # Try with JSON mode first; fall back without it for models that don't support it
    for attempt, use_json_mode in enumerate([True, False]):
        if use_json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        else:
            kwargs.pop("response_format", None)
        try:
            resp = client.chat.completions.create(**kwargs)
            raw  = resp.choices[0].message.content.strip()
            return _parse(raw)
        except Exception as e:
            err = str(e)
            if attempt == 0 and ("response_format" in err.lower() or "json_object" in err.lower()):
                # Model doesn't support JSON mode – retry without it
                print(f"  [LLM] JSON mode not supported by model, retrying without it...")
                continue
            print(f"  [LLM] ERROR: {err[:200]}")
            logger.warning(f"[LLM] API call failed: {err}")
            return _skipped(err[:120])
    return _skipped("all attempts failed")


def _call_gemini(user_prompt: str) -> dict:
    """Google Gemini via google-generativeai SDK."""
    try:
        import google.generativeai as genai
    except ImportError:
        logger.warning("[LLM] google-generativeai not installed. Run: pip install google-generativeai")
        return _skipped("google-generativeai package missing")

    if not LLM_API_KEY:
        return _skipped("no API key")

    try:
        genai.configure(api_key=LLM_API_KEY)
        model = genai.GenerativeModel(
            model_name=LLM_MODEL,
            system_instruction=_SYSTEM_PROMPT,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=LLM_MAX_TOKENS,
                temperature=LLM_TEMPERATURE,
                response_mime_type="application/json",
            ),
        )
        resp = model.generate_content(user_prompt)
        return _parse(resp.text.strip())
    except Exception as e:
        logger.warning(f"[LLM] Gemini call failed: {e}")
        return _skipped(str(e)[:120])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse(raw: str) -> dict:
    """Parse LLM JSON response, tolerating minor formatting issues."""
    try:
        # Strip possible markdown fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)
        verdict = str(data.get("verdict", "WEAK")).upper()
        if verdict not in ("CONFIRM", "WEAK", "REJECT"):
            verdict = "WEAK"
        return {
            "llm_verdict":    verdict,
            "llm_confidence": int(data.get("confidence", 5)),
            "llm_reasoning":  str(data.get("reasoning", ""))[:300],
        }
    except Exception as e:
        logger.warning(f"[LLM] JSON parse failed: {e} | raw={raw[:200]}")
        return _skipped(f"parse error: {e}")


def _skipped(reason: str = "") -> dict:
    return {"llm_verdict": "SKIPPED", "llm_confidence": None, "llm_reasoning": reason}


# ── Public API ────────────────────────────────────────────────────────────────

def validate_signal(sig: dict) -> dict:
    """
    Validate a breakout signal dict using the configured LLM.
    Returns a dict with keys: llm_verdict, llm_confidence, llm_reasoning.
    Merges result back into the original sig dict and returns it.
    """
    if not LLM_API_KEY:
        sig.update(_skipped("LLM_API_KEY not set"))
        return sig

    user_prompt = _build_user_prompt(sig)

    provider = (LLM_PROVIDER or "").lower()
    if provider == "gemini":
        result = _call_gemini(user_prompt)
    else:
        # openai / groq / openrouter all use the same SDK
        result = _call_openai_compat(user_prompt)

    sig.update(result)
    return sig


def validate_signals_batch(signals: list, scan_date: str) -> list:
    """
    Validate a list of signal dicts.
    - First loads today's already-validated verdicts from breakout_log (DB cache).
    - Only hits the LLM API for signals NOT yet validated today.
    - On re-run on the same day: 0 LLM API calls if all signals were already validated.
    - On a new day: full validation run (cache miss for all).
    """
    from data.database import get_llm_verdict_cache

    # Load today's cached verdicts from DB in one query
    verdict_cache = get_llm_verdict_cache(scan_date)   # {symbol: {verdict, conf, reasoning}}
    cached_count  = 0
    api_count     = 0
    total         = len(signals)

    for i, sig in enumerate(signals, 1):
        sig["scan_date"] = scan_date
        symbol = sig.get("symbol")

        # Cache hit — reuse stored verdict, skip API call
        if symbol in verdict_cache:
            sig.update(verdict_cache[symbol])
            cached_count += 1
            print(f"  [LLM {i:>3}/{total}] {symbol:<15} → {sig['llm_verdict']} "
                  f"(cached, no API call)", flush=True)
            continue

        # Cache miss — call LLM
        print(f"  [LLM {i:>3}/{total}] {symbol:<15} ", end="", flush=True)
        validate_signal(sig)
        api_count += 1
        verdict = sig.get("llm_verdict", "SKIPPED")
        conf    = sig.get("llm_confidence")
        conf_str = f"conf={conf}/10" if conf else ""
        print(f"→ {verdict} {conf_str}")

    # Summary
    if cached_count > 0 or api_count > 0:
        print(f"  [LLM] Done. API calls: {api_count} | From cache: {cached_count}")

    return signals
