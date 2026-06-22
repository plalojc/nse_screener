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

LLM_VALIDATION_LIMIT = _env_int("LLM_VALIDATION_LIMIT", 100)

XAI_API_KEY = os.getenv("XAI_API_KEY", "")

REPORT_INCLUDE_WEAK = _env_bool("REPORT_INCLUDE_WEAK", False)
SCAN_TIME_IST = os.getenv("SCAN_TIME_IST", "08:20")
TRADINGVIEW_CHART_ID = os.getenv("TRADINGVIEW_CHART_ID", "IMppZ0T")

# Report composition (admin-controlled). Percentage each category gets of the
# AI-review limit; a category at 0 is excluded from the report entirely.
# Values are normalised at use, so they need not sum to exactly 100.
REPORT_PCT_BREAKOUT = _env_int("REPORT_PCT_BREAKOUT", 50)      # BREAKOUT + PULLBACK
REPORT_PCT_NEWS = _env_int("REPORT_PCT_NEWS", 30)             # NEWS / catalyst
REPORT_PCT_PREBREAKOUT = _env_int("REPORT_PCT_PREBREAKOUT", 10)  # STAGE1
REPORT_PCT_OTHERS = _env_int("REPORT_PCT_OTHERS", 10)        # WATCHLIST / fallback


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

REPORT_SIGNAL_TYPES = {"BREAKOUT", "STAGE1", "PULLBACK", "NEWS", "WATCHLIST"}
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

# == Screening strategy mode (admin-controlled) =============================
# Controls how early in a move the scanner triggers. Set from the admin
# Settings UI -> injected as SCREENING_MODE env var for each scan subprocess.
#   confirmed      - legacy behaviour: confirmed breakouts ranked first
#   pre_breakout   - rank STAGE1 "about to break out" names above breakouts
#   early_breakout - tighten breakout filters so only fresh breaks pass
#   both           - pre-breakout names first AND tightened breakout (recommended)
#   best           - both + only relative-strength leaders (fewer, higher quality)
# Default stays "confirmed" (legacy behaviour); admin opts into the others.
SCREENING_MODE = os.getenv("SCREENING_MODE", "confirmed").strip().lower()
if SCREENING_MODE not in {"confirmed", "pre_breakout", "early_breakout", "both", "best"}:
    SCREENING_MODE = "confirmed"

PREFER_PRE_BREAKOUT = SCREENING_MODE in {"pre_breakout", "both", "best"}
_TIGHTEN_BREAKOUT = SCREENING_MODE in {"early_breakout", "both", "best"}

# "best" mode keeps only relative-strength leaders (top momentum vs the universe).
REQUIRE_RS_LEADERSHIP = SCREENING_MODE == "best"
# Minimum RS rating (1-99) a signal must clear in "best" mode. 70 ≈ top 30%.
BEST_MIN_RS = _env_int("BEST_MIN_RS", 70)

# Max % a breakout close may sit ABOVE its trigger high before it is treated as
# "already extended" and rejected. 99 disables the cap (legacy modes).
MAX_BREAKOUT_ABOVE_TRIGGER_PCT = 3.0 if _TIGHTEN_BREAKOUT else 99.0

if _TIGHTEN_BREAKOUT:
    # Reject extended entries: closer to EMA20, no blow-off candle, not yet overbought.
    MAX_EMA20_EXTENSION_PCT = 6.0
    MAX_DAY_RANGE_ATR = 2.0
    RSI_OVERBOUGHT = 72.0

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

GROK_VALIDATOR_MODEL = "grok-4.20-reasoning"
GROK_VALIDATOR_BATCH_SIZE = 20
GROK_VALIDATOR_MAX_RETRIES = 3
GROK_VALIDATOR_BATCH_DELAY = 1.0
