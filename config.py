
# ============================================================
# config.py – Central configuration
# ============================================================
import os
from dotenv import load_dotenv

# Load .env file first so os.getenv() picks up values from it
load_dotenv(override=False)   # override=False → real env vars win over .env

# ── Upstox ────────────────────────────────────────────────
UPSTOX_ACCESS_TOKEN = os.getenv("UPSTOX_ACCESS_TOKEN", "")
UPSTOX_BASE_URL     = "https://api.upstox.com/v2"
UPSTOX_HIST_URL     = "https://api.upstox.com/v2/historical-candle"

# ── Database ──────────────────────────────────────────────
DB_PATH = "nse_agent.db"

# ── Screener settings ─────────────────────────────────────
LOOKBACK_DAYS        = 365      # days of history to fetch (1 full year)
VOLUME_SURGE_FACTOR  = 1.5      # volume must be 1.5x 20-day avg
RSI_BREAKOUT_MIN     = 55       # RSI above this = momentum
RSI_OVERBOUGHT       = 75       # RSI above this = skip entry
MIN_PRICE            = 20       # ignore penny stocks < ₹20
MAX_PRICE            = 5000     # ignore very expensive stocks
MIN_MARKET_CAP_CR    = 500      # optional filter (₹500 Cr+)
# ── Report output ───────────────────────────────────────────────
REPORT_DIR           = os.getenv("REPORT_DIR", "reports")

# ── Top Picks filter (the actionable shortlist shown at end of scan) ────────
TOP_PICKS_COUNT      = 7        # max stocks to show in the final shortlist
TOP_PICKS_MIN_SCORE  = 10       # must have strong multi-factor confluence
TOP_PICKS_MIN_VOL    = 1.8      # meaningful volume surge (1.8x 20-day avg)
TOP_PICKS_RSI_MAX    = 70       # not overbought (stricter than global 75)
# ── Position / Risk management ───────────────────────────
PROFIT_TARGET_PCT    = 10.0     # ceiling exit at +10% (trailing stop handles the rest)
STOP_LOSS_PCT        = 5.0      # fallback SL % when ATR data is unavailable
MAX_HOLD_DAYS        = 21       # max 3 weeks hold
MAX_OPEN_POSITIONS   = 10       # diversification cap

# ── Volatility-based stop / trail ─────────────────────────
ATR_SL_MULTIPLIER    = 1.5      # initial SL = buy_price − 1.5 × ATR14
ATR_TRAIL_MULTIPLIER = 1.5      # trailing stop = current_price − 1.5 × ATR14

# ── News ──────────────────────────────────────────────────
NEWS_RSS_FEEDS = [
    "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
    "https://www.moneycontrol.com/rss/MCtopnews.xml",
    "https://www.business-standard.com/rss/markets-106.rss",
]

# ── Scheduler ─────────────────────────────────────────────
SCAN_TIME_IST = "08:20"   # run scan 20 min after NSE opens
# ── LLM Validation ─────────────────────────────────────────
# Provider options: "groq" | "openai" | "openrouter" | "gemini" | "ollama"
#
# RECOMMENDED → Groq (paid subscription): https://console.groq.com/keys
#   LLM_PROVIDER = "groq"   (default)
#
# ALTERNATIVE → Ollama (local, no API key, no rate limits):
#   LLM_PROVIDER = "ollama"
#   LLM_MODEL    = "llama3.1:8b"
#
# ALTERNATIVE → Gemini 2.0 Flash (FREE tier): https://aistudio.google.com/apikey
#   LLM_PROVIDER = "gemini"
#   LLM_MODEL    = "gemini-2.0-flash"
#
# ALTERNATIVE → OpenAI GPT-4o-mini (paid): https://platform.openai.com
#   LLM_PROVIDER = "openai"
#   LLM_MODEL    = "gpt-4o-mini"
#   LLM_BASE_URL = ""   # leave blank for default OpenAI endpoint

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq")

# ── Provider-specific defaults (all overridable via .env) ──────────────────
if LLM_PROVIDER == "ollama":
    # Local Ollama — no real API key needed; endpoint is always localhost
    OLLAMA_BASE_URL      = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    LLM_API_KEY          = os.getenv("LLM_API_KEY",          "ollama")         # any non-empty string
    LLM_BASE_URL         = os.getenv("LLM_BASE_URL",         OLLAMA_BASE_URL)
    LLM_MODEL            = os.getenv("LLM_MODEL",            "llama3.1:8b")    # ollama pull llama3.1:8b
    LLM_PANEL_TECH_MODEL = os.getenv("LLM_PANEL_TECH_MODEL", "llama3.1:8b")
    LLM_PANEL_SENT_MODEL = os.getenv("LLM_PANEL_SENT_MODEL", "llama3.1:8b")
    LLM_PANEL_RISK_MODEL = os.getenv("LLM_PANEL_RISK_MODEL", "llama3.1:8b")
    LLM_PANEL_MODERATOR_MODEL = os.getenv("LLM_PANEL_MODERATOR_MODEL", "llama3.1:8b")
else:
    # Groq (paid subscription) — OpenAI-compatible endpoint
    LLM_API_KEY          = os.getenv("LLM_API_KEY",          "")
    LLM_BASE_URL         = os.getenv("LLM_BASE_URL",         "https://api.groq.com/openai/v1")
    LLM_MODEL            = os.getenv("LLM_MODEL",            "meta-llama/llama-4-scout-17b-16e-instruct")
    # ── Panel agent models ──────────────────────────────────────────
    # TECH + RISK + Bull/Bear debate: Scout (fast, math/logic focused)
    # SENTIMENT: llama-3.1-8b-instant (fast NLP for news categorization)
    # MODERATOR (debate Turn 3): Maverick (reads all inputs, makes final call)
    LLM_PANEL_TECH_MODEL = os.getenv("LLM_PANEL_TECH_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
    LLM_PANEL_SENT_MODEL = os.getenv("LLM_PANEL_SENT_MODEL", "llama-3.1-8b-instant")
    LLM_PANEL_RISK_MODEL = os.getenv("LLM_PANEL_RISK_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
    LLM_PANEL_MODERATOR_MODEL = os.getenv("LLM_PANEL_MODERATOR_MODEL", "meta-llama/llama-4-maverick-17b-128e-instruct")

LLM_MAX_TOKENS   = 256    # verdict + confidence + one-line reasoning
LLM_TEMPERATURE  = 0.2    # low temperature for deterministic analysis

# ── Multi-LLM Panel (3-agent ensemble with debate) ─────────────
# Set USE_MULTI_LLM_PANEL=true to enable; falls back to single LLM if panel fails.
# All agents use the same LLM_API_KEY / LLM_BASE_URL.
USE_MULTI_LLM_PANEL  = os.getenv("USE_MULTI_LLM_PANEL", "true").lower() == "true"
LLM_PANEL_MAX_TOKENS = int(os.getenv("LLM_PANEL_MAX_TOKENS", "512"))

# Sequential mode: run panel agents one-at-a-time instead of parallel.
# Use when SENT+RISK share the same model to avoid competing for the same TPM bucket.
# PANEL_AGENT_DELAY: seconds to wait between agent calls in sequential mode.
PANEL_SEQUENTIAL_MODE = os.getenv("PANEL_SEQUENTIAL_MODE", "false").lower() == "true"
PANEL_AGENT_DELAY     = float(os.getenv("PANEL_AGENT_DELAY", "1.0"))

# ── Live Validation (Claude + Web Search) ───────────────────────
# Optional 2nd-pass validation using Claude Opus 4.6 with server-side web search.
# Claude automatically searches the web for real-time news and cites sources.
# Only called for CONFIRM/WEAK signals (not REJECTs) to save quota.
# Pricing: $10 per 1,000 web searches + standard token costs.
# Get API key at: https://console.anthropic.com/settings/keys
USE_LIVE_VALIDATION = os.getenv("USE_LIVE_VALIDATION", "false").lower() == "true"
LIVE_API_KEY        = os.getenv("LIVE_API_KEY", "")     # Anthropic API key
LIVE_MODEL          = os.getenv("LIVE_MODEL", "claude-opus-4-6")

# Configurable prompt — user controls exactly what to ask Gemini.
# Placeholders: {symbol}, {close}, {signal_type}, {stage}, {score},
#               {rsi}, {vol_ratio}, {panel_verdict}, {panel_reasoning}
LIVE_PROMPT_TEMPLATE = os.getenv("LIVE_PROMPT_TEMPLATE", """
You are validating an NSE India stock breakout signal using LIVE real-time data.

Stock: {symbol} at Rs.{close}
Signal: {signal_type} | Stage: {stage} | Score: {score}/20
RSI: {rsi} | Volume: {vol_ratio}x average
Our panel verdict: {panel_verdict} — "{panel_reasoning}"

IMPORTANT — Search the web for current information about {symbol} NSE India:
1. Recent news (last 24-48 hours): earnings, results, orders, SEBI notices
2. Analyst upgrades/downgrades or institutional activity (FII/DII)
3. Promoter activity: pledging, buying, selling
4. Sector/market sentiment that affects this stock
5. Any red flags: fraud, probe, penalty, recall, downgrade

Based on what you find in LIVE search results, return ONLY a JSON object:
{{
  "verdict": "CONFIRM or WEAK or REJECT",
  "confidence": 1-10,
  "reasoning": "2-3 sentences citing specific recent news/events you found",
  "live_catalysts": ["specific recent event 1", "event 2"],
  "live_risks": ["specific risk found"]
}}

Rules:
- If you find NEGATIVE breaking news (SEBI probe, fraud, major loss): verdict REJECT
- If you find POSITIVE catalyst (earnings beat, order win, upgrade): verdict CONFIRM
- If you find NO relevant recent news: verdict WEAK with confidence 5
- Always cite the specific news source and date in your reasoning
""".strip())

# ── MarketAux News/Sentiment API (optional, pluggable) ────────────
# Additional news source with API-scored entity sentiment for NSE stocks.
# Enriches the SENTIMENT agent's prompt alongside existing RSS feeds.
# Free tier: 100 requests/day, 3 articles/request.
# Get API key at: https://www.marketaux.com/account/dashboard
MARKETAUX_ENABLED      = os.getenv("USE_MARKETAUX", "false").lower() == "true"
MARKETAUX_API_KEY      = os.getenv("MARKETAUX_API_KEY", "")
MARKETAUX_MAX_ARTICLES = int(os.getenv("MARKETAUX_MAX_ARTICLES", "3"))
MARKETAUX_RATE_DELAY   = float(os.getenv("MARKETAUX_RATE_DELAY", "0.5"))

# ── Gemini Sentiment Validation (optional, pluggable) ──────────────
# Post-panel validation using Gemini 2.5 Flash + Google Search grounding.
# Runs AFTER the multi-LLM panel on CONFIRM/WEAK signals only.
# Searches the web for recent news and gives its own verdict, which
# can override/modify the panel verdict via an override table.
# Free tier: 500 grounded searches/day, 10 RPM (= 1 call every 6s).
# Tier 1: 1500 grounded/day, 150 RPM.
# Get API key at: https://aistudio.google.com/apikey
# NOTE: After billing setup, check https://aistudio.google.com/apikey
#       for "Action needed" — a one-time prepayment may be required.
GEMINI_SENTIMENT_ENABLED    = os.getenv("USE_GEMINI_SENTIMENT", "false").lower() == "true"
GEMINI_SENTIMENT_API_KEY    = os.getenv("GEMINI_SENTIMENT_API_KEY", "")
GEMINI_SENTIMENT_MODEL      = os.getenv("GEMINI_SENTIMENT_MODEL", "gemini-2.5-flash")
GEMINI_SENTIMENT_RATE_DELAY = float(os.getenv("GEMINI_SENTIMENT_RATE_DELAY", "1.0"))