# ============================================================
# config.py - Central configuration
# ============================================================
import os
from dotenv import load_dotenv

load_dotenv(override=False)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# == User-facing settings ===================================================
# These are the only values a normal user should need to edit in .env.

LLM_VALIDATOR = os.getenv("LLM_VALIDATOR", "gemini").strip().lower()
LLM_VALIDATION_LIMIT = _env_int("LLM_VALIDATION_LIMIT", 100)

GEMINI_VALIDATOR_API_KEY = os.getenv("GEMINI_VALIDATOR_API_KEY", "")
XAI_API_KEY = os.getenv("XAI_API_KEY", "")

REPORT_INCLUDE_WEAK = _env_bool("REPORT_INCLUDE_WEAK", False)
SCAN_TIME_IST = os.getenv("SCAN_TIME_IST", "08:20")
TRADINGVIEW_CHART_ID = os.getenv("TRADINGVIEW_CHART_ID", "IMppZ0T")


# == Internal application defaults =========================================
# Keep these out of env.example. They are product defaults now, and later the
# FastAPI UI can expose only the few that deserve real controls.

DB_PATH = "nse_agent.db"
NSE_BHAVCOPY_DB_PATH = "nse_bhavcopy.db"
NSE_BHAVCOPY_DIR = "data/bhavcopy"
REPORT_DIR = "reports"  # backtest/manual exports; scan reports are rendered from DB

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN", "")
DB_BACKEND = os.getenv(
    "DB_BACKEND",
    "postgres" if DATABASE_URL else "sqlite",
).strip().lower()
DB_SYSTEM_SCHEMA = os.getenv("DB_SYSTEM_SCHEMA", "system").strip() or "system"
DB_USER_SCHEMA = os.getenv("DB_USER_SCHEMA", "app_user").strip() or "app_user"

REPORT_SIGNAL_TYPES = {"BREAKOUT", "STAGE1", "PULLBACK", "NEWS"}
REPORT_INCLUDE_REJECTED = False
REPORT_INCLUDE_SKIPPED = False

SCAN_SIGNAL_TYPES = {"BREAKOUT", "STAGE1", "PULLBACK"}

LOOKBACK_DAYS = 365
VOLUME_SURGE_FACTOR = 1.5
RSI_BREAKOUT_MIN = 55.0
RSI_OVERBOUGHT = 80.0
MIN_PRICE = 20.0
MAX_PRICE = 5000.0
MIN_TURNOVER_CR = 5.0
MIN_BREAKOUT_SCORE = 8
MAX_EMA20_EXTENSION_PCT = 10.0
MAX_DAY_RANGE_ATR = 2.8
MIN_CLOSE_RANGE_POS = 0.55
MIN_STAGE1_SCORE = 6
STAGE1_NEAR_BREAKOUT_PCT = 5.0
STAGE1_RSI_MIN = 45.0
STAGE1_RSI_MAX = 68.0

TOP_PICKS_COUNT = 7
TOP_PICKS_MIN_SCORE = 10
TOP_PICKS_MIN_VOL = 1.8
TOP_PICKS_RSI_MAX = 75.0

PROFIT_TARGET_PCT = 10.0
STOP_LOSS_PCT = 5.0
MAX_HOLD_DAYS = 21
MAX_OPEN_POSITIONS = 10
ATR_SL_MULTIPLIER = 1.5
ATR_TRAIL_MULTIPLIER = 1.5

ENABLE_CATALYST_NEWS = True
ENABLE_ONLINE_THEME_SOURCES = True
CATALYST_LOOKBACK_DAYS = 7
MAX_CATALYST_CANDIDATES = 50
MIN_CATALYST_SCORE = 5
CATALYST_SOURCE_TIMEOUT = 12.0
MAX_POLICY_SYMBOLS_PER_EVENT = 20
MIN_NEWS_TURNOVER_CR = 2.0
MIN_NEWS_TECH_SCORE = 4
NEWS_MAX_EMA20_EXTENSION_PCT = 14.0

LLM_FILL_TO_LIMIT = True
MIN_WATCHLIST_SCORE = 5
MIN_WATCHLIST_TURNOVER_CR = 2.0
WATCHLIST_NEAR_HIGH_PCT = 12.0

GEMINI_VALIDATOR_MODEL = "gemini-2.5-flash"
GEMINI_VALIDATOR_RATE_DELAY = 6.0
GEMINI_VALIDATOR_CONCURRENCY = 10

GROK_VALIDATOR_MODEL = "grok-4.20-reasoning"
GROK_VALIDATOR_BATCH_SIZE = 20
GROK_VALIDATOR_MAX_RETRIES = 3
GROK_VALIDATOR_BATCH_DELAY = 1.0
