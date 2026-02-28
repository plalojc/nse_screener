
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
LOOKBACK_DAYS        = 90       # days of history to fetch
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
# Provider options: "groq" | "openai" | "openrouter" | "gemini"
#
# RECOMMENDED → Groq (FREE, fastest): https://console.groq.com/keys
LLM_PROVIDER  = "groq"
LLM_MODEL     = "llama-3.3-70b-versatile"
LLM_BASE_URL  = "https://api.groq.com/openai/v1"
#
# ALTERNATIVE  → Gemini 2.0 Flash (FREE tier): https://aistudio.google.com/apikey
#   LLM_PROVIDER  = "gemini"
#   LLM_MODEL     = "gemini-2.0-flash"
#
# ALTERNATIVE  → OpenAI GPT-4o-mini (paid, reliable): https://platform.openai.com
#   LLM_PROVIDER  = "openai"
#   LLM_MODEL     = "gpt-4o-mini"
#   LLM_BASE_URL  = ""   # leave blank for default OpenAI endpoint

LLM_PROVIDER     = os.getenv("LLM_PROVIDER",  "groq")
LLM_MODEL        = os.getenv("LLM_MODEL",     "llama-3.3-70b-versatile")
LLM_API_KEY      = os.getenv("LLM_API_KEY",   "")   # set in .env or environment
LLM_BASE_URL     = os.getenv("LLM_BASE_URL",  "https://api.groq.com/openai/v1")
LLM_MAX_TOKENS   = 256    # verdict + confidence + one-line reasoning
LLM_TEMPERATURE  = 0.2    # low temperature for deterministic analysis