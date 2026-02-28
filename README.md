# NSE Breakout Agent

An automated stock screener for NSE (India) equities that detects breakout and pullback setups, validates signals using an LLM, manages a paper-trade portfolio with ATR-based stops, and keeps a full date-wise history of every signal.

---

## Table of Contents

- [Features](#features)
- [Project Structure](#project-structure)
- [Architecture](#architecture)
- [Signal Detection Logic](#signal-detection-logic)
- [LLM Validation](#llm-validation)
- [Database Schema](#database-schema)
- [Configuration](#configuration)
- [Setup & Installation](#setup--installation)
- [Usage](#usage)
- [Risk Management](#risk-management)
- [Data Flow](#data-flow)

---

## Features

| Feature | Detail |
|---|---|
| **Full NSE EQ universe** | Scans all NSE equity instruments via Upstox live instruments feed |
| **Two signal types** | Momentum Breakout + MA Pullback (buy-the-dip) |
| **Scoring engine** | 9-criteria weighted score (max ~20); threshold ≥ 7 to emit a signal |
| **LLM validation** | Every signal sent to Groq / Gemini / OpenAI for CONFIRM / WEAK / REJECT verdict |
| **SQLite cache** | OHLCV data cached; only fetches fresh data for symbols without up-to-date history |
| **ATR-based risk** | Initial SL = close − 1.5×ATR14, ratcheted trailing stop updated every scan |
| **Portfolio tracker** | Tracks open positions; exits on profit target, trailing stop, or max hold days |
| **Breakout log** | Date-wise history of every signal + LLM verdict stored in SQLite |
| **Scheduler** | APScheduler cron job runs automatically at 09:20 IST Mon–Fri |

---

## Project Structure

```
nse_breakout_agent/
│
├── main.py                  # CLI entry point
├── config.py                # All settings (API keys, thresholds, LLM config)
├── scheduler.py             # APScheduler daily cron runner (09:20 IST)
├── requirements.txt
├── nse_agent.db             # SQLite database (auto-created on first run)
│
├── agent/
│   ├── screener_agent.py    # Main orchestrator – runs the full 5-step scan pipeline
│   └── portfolio_tracker.py # Open position tracker, exit signal checker
│
├── analysis/
│   ├── technical.py         # Indicator computation via pandas-ta
│   ├── breakout_scanner.py  # Breakout + MA pullback signal logic
│   ├── llm_validator.py     # LLM signal validation (Groq / OpenAI / Gemini)
│   └── news_fetcher.py      # RSS news fetcher and SQLite cache
│
└── data/
    ├── upstox_client.py     # Upstox v2 REST API client (historical OHLCV)
    └── database.py          # SQLite layer – all table definitions and CRUD helpers
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        main.py / scheduler                       │
│                (CLI commands: scan | portfolio | log)            │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    screener_agent.py                             │
│                                                                  │
│  Step 1 ► Check exit conditions on open positions               │
│  Step 2 ► Fetch & cache market news (RSS)                       │
│  Step 3 ► Scan NSE EQ universe                                  │
│           ┌──────────────────────────────────────┐              │
│           │  For each symbol:                    │              │
│           │  • Load from SQLite cache if fresh   │              │
│           │  • Else fetch from Upstox API        │              │
│           │  • Run breakout_scanner              │              │
│           └──────────────────────────────────────┘              │
│  Step 4 ► LLM validation for every signal found                 │
│           → save_breakout_log() [date-wise history]             │
│  Step 5 ► Display results + auto-enter Stage2 positions         │
└──────┬──────────────┬──────────────┬────────────────────────────┘
       │              │              │
       ▼              ▼              ▼
┌────────────┐ ┌───────────┐ ┌──────────────────────┐
│ Upstox v2  │ │ pandas-ta │ │   LLM Provider        │
│ REST API   │ │indicators │ │  Groq / OpenAI /      │
│ (OHLCV)    │ │           │ │  Gemini / OpenRouter  │
└─────┬──────┘ └─────┬─────┘ └──────────┬───────────┘
      │              │                   │
      └──────────────┴───────────────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │     SQLite DB         │
              │  • ohlcv              │
              │  • breakout_log       │
              │  • positions          │
              │  • signals            │
              │  • news_cache         │
              └───────────────────────┘
```

---

## Signal Detection Logic

### Breakout Scanner (`is_breakout`)

Nine scoring criteria — minimum score of **7** required to emit a signal:

| # | Criterion | Points |
|---|---|---|
| 1 | 20-day high breakout **+** volume ≥ 2× average | +3 |
| | Plain volume surge ≥ 1.5× average (without price breakout) | +1 |
| 2 | RSI 55–75 (momentum zone, not overbought) | +2 |
| 3 | Close > EMA20 > EMA50 (trend alignment) | +2 |
| 4 | MACD histogram bullish crossover | +2 |
| | MACD crossover while MACD line still negative (high-potential) | +4 |
| 5 | Close ≥ Bollinger Band upper | +2 |
| 6 | Within 3% of 52-week high | +3 |
| 7 | EMA20/50 golden cross in last 5 days | +3 |
| 8 | Supertrend fresh flip to bullish | +3 |
| | Supertrend already bullish (confirmation) | +1 |
| 9 | Close > EMA200 (macro uptrend filter) | +1 |

### MA Pullback Scanner (`is_ma_pullback`)

All four conditions must be true (pass/fail, no scoring):

1. EMA50 > EMA200 — macro uptrend confirmed  
2. Candle low ≤ EMA50 — price dipped to the 50 EMA  
3. Candle close > EMA50 — buyers defended the level  
4. RSI < 45 — short-term oversold

---

## LLM Validation

After scanning, every detected signal is sent to a language model for independent validation. The model receives full technical context and recent news headlines and returns:

```json
{
  "verdict":    "CONFIRM | WEAK | REJECT",
  "confidence": 8,
  "reasoning":  "Strong breakout above 20d high with 2.4x volume; RSI 63 in momentum zone."
}
```

### Supported Providers

| Provider | Model | Cost | Notes |
|---|---|---|---|
| **Groq** ⭐ (default) | `llama-3.3-70b-versatile` | **Free** | Fastest (~300 tok/s). Recommended. |
| Google Gemini | `gemini-2.0-flash` | Free tier | 1M context window |
| OpenAI | `gpt-4o-mini` | ~$0.15/M tokens | Reliable JSON mode |
| OpenRouter | Any above | Per-model | Single key for all providers |

Set `LLM_API_KEY` in your environment or `.env` file. If not set, validation is skipped and `llm_verdict = SKIPPED`.

---

## Database Schema

### `ohlcv`
OHLCV price cache (symbol × date, primary key).

### `breakout_log` ← date-wise signal history
| Column | Type | Description |
|---|---|---|
| `scan_date` | TEXT | Date the signal was detected |
| `symbol` | TEXT | NSE trading symbol |
| `signal_type` | TEXT | BREAKOUT or PULLBACK |
| `close`, `rsi`, `vol_ratio`, `score` | REAL/INT | Signal metrics |
| `stage` | TEXT | Stage1 / Stage2 / Stage3 |
| `ema20`, `ema50`, `atr14`, `swing_low` | REAL | Technical levels |
| `reasons` | TEXT | Screener rule triggers |
| `llm_verdict` | TEXT | CONFIRM / WEAK / REJECT / SKIPPED |
| `llm_confidence` | INT | 1–10 |
| `llm_reasoning` | TEXT | One-line LLM explanation |

### `positions`
Open and closed paper-trade positions with buy price, target, SL, trailing stop, exit details, and PnL %.

### `signals`
Log of every BUY/SELL signal with date, price, and reason.

### `news_cache`
RSS article cache (title, URL, published date, source).

---

## Configuration

All settings live in `config.py` and can be overridden via environment variables or a `.env` file.

```python
# --- Upstox ---
UPSTOX_ACCESS_TOKEN  # Upstox OAuth2 bearer token

# --- Screener ---
LOOKBACK_DAYS       = 90      # OHLCV history to fetch per symbol
VOLUME_SURGE_FACTOR = 1.5     # minimum volume ratio for plain surge (+1)
RSI_BREAKOUT_MIN    = 55      # RSI lower bound for momentum zone
RSI_OVERBOUGHT      = 75      # RSI upper bound (skip overbought)
MIN_PRICE           = 20      # exclude stocks below ₹20
MAX_PRICE           = 5000    # exclude stocks above ₹5000

# --- Risk Management ---
PROFIT_TARGET_PCT   = 10.0    # flat ceiling exit %
STOP_LOSS_PCT       = 5.0     # fallback SL % (when ATR unavailable)
MAX_HOLD_DAYS       = 21      # max position hold in days
MAX_OPEN_POSITIONS  = 10      # max simultaneous open positions
ATR_SL_MULTIPLIER   = 1.5     # initial SL = price − 1.5×ATR14
ATR_TRAIL_MULTIPLIER= 1.5     # trailing stop = current − 1.5×ATR14

# --- LLM ---
LLM_PROVIDER        = "groq"
LLM_MODEL           = "llama-3.3-70b-versatile"
LLM_API_KEY         = ""      # set in environment
LLM_BASE_URL        = "https://api.groq.com/openai/v1"
LLM_MAX_TOKENS      = 256
LLM_TEMPERATURE     = 0.2

# --- Scheduler ---
SCAN_TIME_IST       = "09:20" # 20 min after NSE open
```

---

## Setup & Installation

### 1. Clone / open the project

```bash
cd nse_breakout_agent
```

### 2. Create a virtual environment (recommended)

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux
```

### 3. Install dependencies

```bash
pip install -r requirements.txt

# Optional: Gemini support
pip install google-generativeai
```

### 4. Create a `.env` file

```env
# Upstox (required) — generate token at https://upstox.com/developer/
UPSTOX_ACCESS_TOKEN=your_upstox_token_here

# LLM (optional but recommended) — free key at https://console.groq.com/keys
LLM_API_KEY=your_groq_key_here
LLM_PROVIDER=groq
LLM_MODEL=llama-3.3-70b-versatile
LLM_BASE_URL=https://api.groq.com/openai/v1
```

### 5. Run

```bash
python main.py scan
```

---

## Usage

```bash
# Run full scan (downloads data, detects signals, LLM validates, enters positions)
python main.py scan

# Scan against a specific past date (backtesting / weekend runs)
python main.py scan --date 2026-02-27

# View current open portfolio
python main.py portfolio

# View date-wise breakout history (last 30 days)
python main.py log

# View last 7 days only
python main.py log --days 7

# Run as a scheduled daemon (auto-runs at 09:20 IST Mon–Fri)
python main.py schedule
```

### Sample scan output

```
============================================================
   NSE BREAKOUT AGENT – DAILY SCAN
============================================================
   Scan date : 2026-02-27

[1/5] Checking exit conditions...
  No exits triggered.

[2/5] Fetching market news...
  12 new articles cached.

[3/5] Loading NSE EQ universe...
  Universe: 1847 NSE EQ instruments.
  Done. Downloaded: 43 | From cache: 1798 | Skipped (open pos): 6

[4/5] LLM validation (5 signal(s))...
  [LLM 1/5] RELIANCE       → CONFIRM conf=8/10
  [LLM 2/5] HDFCBANK       → WEAK    conf=5/10
  [LLM 3/5] TATAMOTORS     → CONFIRM conf=9/10
  ...

  5 signal(s) saved to breakout_log.

[5/5] Results: 5 breakout candidate(s) found.

╒═══════════╤══════════╤═════════╤══════╤══════╤═══════╤════════╤══════════════╤═══════════════╕
│ Type      │ Symbol   │ Price   │  RSI │ Vol  │ Score │ Stage  │ LLM          │ Reason        │
╞═══════════╪══════════╪═════════╪══════╪══════╪═══════╪════════╪══════════════╪═══════════════╡
│ BREAKOUT  │ RELIANCE │ ₹1284.5 │ 63.2 │ 2.4x │    14 │ Stage2 │ CONFIRM(8/10)│ 20d breakout..│
...
```

---

## Risk Management

The agent uses a layered exit strategy applied in priority order on every portfolio check:

```
1. STORED TARGET HIT   → exit when price ≥ calculated 2R target (ATR-based)
2. PROFIT TARGET %     → fallback ceiling at +10% (configurable)
3. TRAILING STOP       → current_price − 1.5×ATR14, ratcheted UP only (never down)
4. MAX HOLD DAYS       → forced exit after 21 days regardless of PnL
```

**Stop loss calculation at entry:**
```
SL_atr   = buy_price − 1.5 × ATR14
SL_swing = swing_low × 0.99          (most recent local trough)
SL       = max(SL_atr, SL_swing)     ← tightest valid stop above zero
```

**Target calculation at entry:**
```
risk     = buy_price − SL
target   = buy_price + (risk × 2)    ← 2R reward-to-risk ratio
```

---

## Data Flow

```
Upstox API
    │  GET /v2/historical-candle/{instrument_key}/day/{to}/{from}
    ▼
upstox_client.py   ──► instruments JSON (NSE.json.gz) → symbol→key map
    │
    ▼
database.py        ──► ohlcv table  (cache; keyed by symbol+date)
    │
    ▼
technical.py       ──► EMA20/50/200, RSI, MACD, Bollinger, ATR14,
                        Volume ratio, Supertrend, 20d high, 52w high/low
    │
    ▼
breakout_scanner.py ─► score-based breakout signal  OR  pullback signal
    │
    ▼
news_fetcher.py    ──► merge recent headlines into signal dict
    │
    ▼
llm_validator.py   ──► POST to Groq/OpenAI/Gemini → verdict + confidence
    │
    ▼
database.py        ──► save_breakout_log()   (breakout_log table)
                   ──► open_position()       (positions table)
                   ──► save_signal()         (signals table)
```
