# ============================================================
# config.py - Central configuration
# ============================================================
import os
from dotenv import load_dotenv

load_dotenv(override=False)

# Database and reports
DB_PATH = os.getenv("DB_PATH", "nse_agent.db")
NSE_BHAVCOPY_DB_PATH = os.getenv("NSE_BHAVCOPY_DB_PATH", "nse_bhavcopy.db")
NSE_BHAVCOPY_DIR = os.getenv("NSE_BHAVCOPY_DIR", "data/bhavcopy")
REPORT_DIR = os.getenv("REPORT_DIR", "reports")
REPORT_SIGNAL_TYPES = {
    item.strip().upper()
    for item in os.getenv("REPORT_SIGNAL_TYPES", "BREAKOUT").split(",")
    if item.strip()
}
REPORT_INCLUDE_WEAK = os.getenv("REPORT_INCLUDE_WEAK", "false").lower() == "true"
REPORT_INCLUDE_REJECTED = os.getenv("REPORT_INCLUDE_REJECTED", "false").lower() == "true"
REPORT_INCLUDE_SKIPPED = os.getenv("REPORT_INCLUDE_SKIPPED", "false").lower() == "true"

# Screener settings
SCAN_SIGNAL_TYPES = {
    item.strip().upper()
    for item in os.getenv("SCAN_SIGNAL_TYPES", "BREAKOUT").split(",")
    if item.strip()
}
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "365"))
VOLUME_SURGE_FACTOR = float(os.getenv("VOLUME_SURGE_FACTOR", "1.5"))
RSI_BREAKOUT_MIN = float(os.getenv("RSI_BREAKOUT_MIN", "55"))
RSI_OVERBOUGHT = float(os.getenv("RSI_OVERBOUGHT", "80"))
MIN_PRICE = float(os.getenv("MIN_PRICE", "20"))
MAX_PRICE = float(os.getenv("MAX_PRICE", "5000"))
MIN_TURNOVER_CR = float(os.getenv("MIN_TURNOVER_CR", "5"))
MIN_BREAKOUT_SCORE = int(os.getenv("MIN_BREAKOUT_SCORE", "8"))
MAX_EMA20_EXTENSION_PCT = float(os.getenv("MAX_EMA20_EXTENSION_PCT", "10"))
MAX_DAY_RANGE_ATR = float(os.getenv("MAX_DAY_RANGE_ATR", "2.8"))
MIN_CLOSE_RANGE_POS = float(os.getenv("MIN_CLOSE_RANGE_POS", "0.55"))

# Top picks filter
TOP_PICKS_COUNT = int(os.getenv("TOP_PICKS_COUNT", "7"))
TOP_PICKS_MIN_SCORE = int(os.getenv("TOP_PICKS_MIN_SCORE", "10"))
TOP_PICKS_MIN_VOL = float(os.getenv("TOP_PICKS_MIN_VOL", "1.8"))
TOP_PICKS_RSI_MAX = float(os.getenv("TOP_PICKS_RSI_MAX", "75"))

# Position and risk management
PROFIT_TARGET_PCT = float(os.getenv("PROFIT_TARGET_PCT", "10.0"))
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "5.0"))
MAX_HOLD_DAYS = int(os.getenv("MAX_HOLD_DAYS", "21"))
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "10"))
ATR_SL_MULTIPLIER = float(os.getenv("ATR_SL_MULTIPLIER", "1.5"))
ATR_TRAIL_MULTIPLIER = float(os.getenv("ATR_TRAIL_MULTIPLIER", "1.5"))

# News
NEWS_RSS_FEEDS = [
    "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
    "https://www.moneycontrol.com/rss/MCtopnews.xml",
    "https://www.business-standard.com/rss/markets-106.rss",
]

# Scheduler
SCAN_TIME_IST = os.getenv("SCAN_TIME_IST", "08:20")

# LLM validator: "gemini" or "grok".
LLM_VALIDATOR = os.getenv("LLM_VALIDATOR", "gemini").lower()
LLM_VALIDATION_LIMIT = int(os.getenv("LLM_VALIDATION_LIMIT", "100"))

# Gemini decision engine
GEMINI_VALIDATOR_API_KEY = os.getenv("GEMINI_VALIDATOR_API_KEY", "")
GEMINI_VALIDATOR_MODEL = os.getenv("GEMINI_VALIDATOR_MODEL", "gemini-2.5-flash")
GEMINI_VALIDATOR_RATE_DELAY = float(os.getenv("GEMINI_VALIDATOR_RATE_DELAY", "6.0"))
GEMINI_VALIDATOR_CONCURRENCY = int(os.getenv("GEMINI_VALIDATOR_CONCURRENCY", "10"))

# Grok decision engine (xAI OpenAI-compatible API)
XAI_API_KEY = os.getenv("XAI_API_KEY", "")
GROK_VALIDATOR_MODEL = os.getenv("GROK_VALIDATOR_MODEL", "grok-4.20-reasoning")
GROK_VALIDATOR_BATCH_SIZE = int(os.getenv("GROK_VALIDATOR_BATCH_SIZE", "10"))
GROK_VALIDATOR_MAX_RETRIES = int(os.getenv("GROK_VALIDATOR_MAX_RETRIES", "3"))
GROK_VALIDATOR_BATCH_DELAY = float(os.getenv("GROK_VALIDATOR_BATCH_DELAY", "1.0"))
