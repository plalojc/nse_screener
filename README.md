# NSE Breakout Agent

An automated stock screener for NSE (India) equities that detects breakout and pullback setups, validates signals through a multi-LLM panel with bull/bear debate, manages a paper-trade portfolio with ATR-based stops, and keeps a full date-wise history of every signal.

---

## Table of Contents

- [Features](#features)
- [Project Structure](#project-structure)
- [Architecture](#architecture)
- [Multi-LLM Panel](#multi-llm-panel)
- [Signal Detection Logic](#signal-detection-logic)
- [Advanced Pattern Detection](#advanced-pattern-detection)
- [Live Validation](#live-validation)
- [Database Schema](#database-schema)
- [Configuration](#configuration)
- [Setup & Installation](#setup--installation)
- [Usage](#usage)
- [Backtesting & Validation](#backtesting--validation)
- [Risk Management](#risk-management)
- [Data Flow](#data-flow)

---

## Features

| Feature | Detail |
|---|---|
| **Full NSE EQ universe** | Scans all NSE equity instruments via Upstox live instruments feed |
| **Two signal types** | Momentum Breakout + MA Pullback (buy-the-dip) |
| **Scoring engine** | 9-criteria weighted score (max ~20); threshold >= 7 to emit a signal |
| **Multi-LLM Panel** | 3-agent ensemble (Technical, Sentiment, Risk) with weighted consensus + bull/bear debate |
| **Advanced Patterns** | VCP (Minervini) and Bull Flag detection with bonus scoring |
| **Sentiment Analysis** | News RSS + structured sentiment scoring before LLM call |
| **MarketAux Integration** | Optional pluggable news source with API-scored entity sentiment for NSE stocks |
| **Gemini Validation** | Optional post-panel validation via Gemini 2.5 Flash + Google Search grounding |
| **Live Validation** | Optional post-panel validation via Claude Opus 4.6 + web search for real-time news check |
| **SQLite cache** | OHLCV data cached; only fetches fresh data for symbols without up-to-date history |
| **ATR-based risk** | Initial SL = close - 1.5 x ATR14, ratcheted trailing stop updated every scan |
| **Portfolio tracker** | Tracks open positions; exits on profit target, trailing stop, or max hold days |
| **Breakout log** | Date-wise history of every signal + per-agent verdicts stored in SQLite |
| **HTML Reports** | Full-colour HTML report generated after every scan and every backtest run |
| **Backtesting** | Re-run screener on any past date using cached DB data; validate against real forward price action |
| **Rate-limit hardening** | Exponential backoff (1-2-4-8s) for 429 errors + optional sequential agent mode |
| **Scheduler** | APScheduler cron job runs automatically at 09:20 IST Mon-Fri |

---

## Project Structure

```
nse_breakout_agent/
|
|-- main.py                  # CLI entry point (scan, portfolio, log, backtest, schedule)
|-- config.py                # All settings (API keys, thresholds, LLM models)
|-- scheduler.py             # APScheduler daily cron runner (09:20 IST)
|-- requirements.txt
|-- nse_agent.db             # SQLite database (auto-created on first run)
|
|-- agent/
|   |-- screener_agent.py    # Main orchestrator - runs the full 5-step scan pipeline
|   |-- portfolio_tracker.py # Open position tracker, exit signal checker
|
|-- analysis/
|   |-- technical.py         # Indicator computation via pandas-ta
|   |-- breakout_scanner.py  # Breakout + MA pullback signal logic
|   |-- pattern_scanner.py   # VCP (Minervini) + Bull Flag pattern detection
|   |-- sentiment_scorer.py  # Structured news sentiment scoring (no LLM)
|   |-- news_fetcher.py      # RSS news fetcher and SQLite cache
|   |-- llm_panel.py         # Multi-LLM panel: 3 agents + debate + consensus
|   |-- llm_validator.py     # Single-LLM fallback validator (Groq/OpenAI/Gemini)
|   |-- marketaux_client.py  # MarketAux.com API client (pluggable news sentiment)
|   |-- gemini_sentiment.py  # Post-panel: Gemini 2.5 Flash + Google Search validation
|   |-- live_validator.py    # Post-panel: Claude Opus 4.6 + web search validation
|   |-- backtester.py        # Past-date signal replay + forward outcome evaluation
|
|-- data/
|   |-- upstox_client.py     # Upstox v2 REST API client (historical OHLCV)
|   |-- database.py          # SQLite layer - all table definitions and CRUD helpers
|
|-- report/
|   |-- html_report_writer.py       # HTML report for live scan results
|   |-- backtest_report_writer.py   # HTML validation report for backtest results
```

---

## Architecture

```
                          main.py / scheduler
                 (CLI: scan | portfolio | log | backtest)
                               |
                               v
                      screener_agent.py
    ============================================================
    Step 1  Check exit conditions on open positions
    Step 2  Fetch & cache market news (RSS)
    Step 3  Scan NSE EQ universe (~1800 symbols)
              - Load from SQLite cache if fresh
              - Else fetch from Upstox API
              - Run breakout_scanner + pattern_scanner
    Step 4  Multi-LLM Panel validation (per signal)
              +-- [4b] Live Validation (Claude + Web Search)
    Step 5  Display results + auto-enter Stage2 positions
              +-- HTML report generation
    ============================================================
              |                  |                  |
              v                  v                  v
       +------------+    +-------------+    +--------------+
       | Upstox v2  |    |  pandas-ta  |    | Groq API     |
       | REST API   |    |  indicators |    | (Scout +     |
       | (OHLCV)    |    |             |    |  Maverick)   |
       +-----+------+    +------+------+    +------+-------+
             |                  |                  |
             +------------------+------------------+
                               |
                               v
                    +---------------------+
                    |     SQLite DB       |
                    |  - instruments      |
                    |  - ohlcv            |
                    |  - breakout_log     |
                    |  - positions        |
                    |  - signals          |
                    |  - news_cache       |
                    +---------------------+
```

---

## Multi-LLM Panel

The core validation engine uses a 3-agent ensemble with weighted consensus and an automated debate mechanism, inspired by the TradingAgents (2024-2025) research paper.

### Model Assignment (Groq)

| Role | Model | Why |
|---|---|---|
| **TECHNICAL Analyst** | `llama-4-scout` | Fast, math/logic focused, chart pattern analysis |
| **SENTIMENT Analyst** | `llama-3.1-8b-instant` | Quick NLP, news categorization as positive/negative |
| **RISK Manager** | `llama-4-scout` | Stop loss quality, R:R assessment, tail risk analysis |
| **Bull Debater** | `llama-4-scout` | Argues FOR the trade with specific data points |
| **Bear Debater** | `llama-4-scout` | Argues AGAINST the trade, identifies risks |
| **MODERATOR** | `llama-4-maverick` | Reads all inputs, makes final CONFIRM/REJECT decision |

### How It Works

```
Step 1: Pre-compute (no LLM)
    - Pattern scan (VCP, Bull Flag) -> bonus score
    - News fetch + sentiment scoring -> structured report
    - Open position count -> risk context

Step 2: 3 Agents in Parallel (or sequential mode)
    +-- TECHNICAL (Scout) -> verdict + confidence + reasoning
    +-- SENTIMENT (Scout) -> verdict + confidence + reasoning
    +-- RISK      (Scout) -> verdict + confidence + reasoning

Step 3: Weighted Consensus
    Score = TECH x 0.40 + SENT x 0.35 + RISK x 0.25
    CONFIRM >= 0.68 | WEAK >= 0.38 | else REJECT

Step 4: Debate (auto-triggered when needed)
    Triggers when:
      - TECHNICAL=CONFIRM and SENTIMENT=REJECT (fundamental conflict)
      - Any CONFIRM and RISK=REJECT (risk veto)
      - Weighted score in grey zone [0.38, 0.68]

    Turn 1: Bull Researcher (Scout) argues FOR
    Turn 2: Bear Researcher (Scout) argues AGAINST
    Turn 3: Fund Manager (Maverick) makes final call
                -> overrides weighted consensus

Step 5: Final Verdict
    If debate triggered -> use Moderator's verdict
    Else -> use weighted consensus verdict
```

### Fallback Chain

```
Multi-LLM Panel fails -> Single-LLM fallback (llm_validator.py)
Single-LLM fails     -> verdict = SKIPPED
```

### Rate-Limit Hardening

- **Exponential backoff**: `_call_llm()` retries up to 4 times on HTTP 429 errors (waits 1s, 2s, 4s, 8s)
- **Sequential mode**: Set `PANEL_SEQUENTIAL_MODE=true` to run agents one-at-a-time with configurable delay
- **Verdict cache**: Re-running scan on the same day uses cached verdicts (zero API calls)

---

## Signal Detection Logic

### Breakout Scanner (`is_breakout`)

Nine scoring criteria -- minimum score of **7** required to emit a signal:

| # | Criterion | Points |
|---|---|---|
| 1 | 20-day high breakout **+** volume >= 2x average | +3 |
| | Plain volume surge >= 1.5x average (without price breakout) | +1 |
| 2 | RSI 55-75 (momentum zone, not overbought) | +2 |
| 3 | Close > EMA20 > EMA50 (trend alignment) | +2 |
| 4 | MACD histogram bullish crossover | +2 |
| | MACD crossover while MACD line still negative (high-potential) | +4 |
| 5 | Close >= Bollinger Band upper | +2 |
| 6 | Within 3% of 52-week high | +3 |
| 7 | EMA20/50 golden cross in last 5 days | +3 |
| 8 | Supertrend fresh flip to bullish | +3 |
| | Supertrend already bullish (confirmation) | +1 |
| 9 | Close > EMA200 (macro uptrend filter) | +1 |

### MA Pullback Scanner (`is_ma_pullback`)

All four conditions must be true (pass/fail, no scoring):

1. EMA50 > EMA200 -- macro uptrend confirmed
2. Candle low <= EMA50 -- price dipped to the 50 EMA
3. Candle close > EMA50 -- buyers defended the level
4. RSI < 45 -- short-term oversold

---

## Advanced Pattern Detection

The pattern scanner (`analysis/pattern_scanner.py`) adds bonus scoring to signals:

### VCP (Volatility Contraction Pattern - Minervini)

Detects progressively tightening price contractions before a breakout. Requires >= 65 bars of data. Adds **+2 bonus points** to the signal score when detected.

### Bull Flag

Detects a strong impulse move followed by a tight consolidation channel. Requires >= 25 bars. Adds **+2 bonus points** when detected.

Pattern badges appear in the Top Picks display:
```
#1  RELIANCE     Rs.1284.50  Score:16  RSI:63  Vol:2.4x  LLM:CONFIRM(8/10) [VCP] [FLAG]
```

---

## Live Validation

Optional 2nd-pass validation using Claude Opus 4.6 with server-side web search (Step 4b).

| Setting | Value |
|---|---|
| **Provider** | Anthropic (Claude) |
| **Model** | `claude-opus-4-6` (default) |
| **Method** | Server-side web search (`web_search_20250305`) — Claude searches the web automatically and cites sources |
| **Cost** | $10 per 1,000 web searches + standard token costs ([pricing](https://docs.anthropic.com/en/docs/build-with-claude/tool-use/web-search)) |
| **Triggers on** | CONFIRM and WEAK signals only (skips REJECTs to save quota) |
| **Max searches** | 3 per signal (configurable via `max_uses`) |

### What it checks

1. Recent news (last 24-48 hours): earnings, results, orders, SEBI notices
2. Analyst upgrades/downgrades or institutional activity (FII/DII)
3. Promoter activity: pledging, buying, selling
4. Sector/market sentiment
5. Red flags: fraud, probe, penalty, downgrade

### Override Logic

The live verdict can override the panel verdict:

| Panel | Live | Final |
|---|---|---|
| CONFIRM | CONFIRM | CONFIRM |
| CONFIRM | WEAK | WEAK |
| CONFIRM | REJECT | WEAK |
| WEAK | CONFIRM | CONFIRM |
| WEAK | WEAK | WEAK |
| WEAK | REJECT | REJECT |

### Setup

```bash
pip install anthropic
```

```env
USE_LIVE_VALIDATION=true
LIVE_API_KEY=sk-ant-your_key_here    # get from https://console.anthropic.com/settings/keys
LIVE_MODEL=claude-opus-4-6
```

---

## MarketAux Integration

Optional pluggable news source that enriches the SENTIMENT agent with API-scored entity sentiment from [MarketAux.com](https://www.marketaux.com).

| Setting | Value |
|---|---|
| **Provider** | MarketAux.com |
| **Method** | REST API (`GET /v1/news/all`) with entity-level sentiment scores |
| **NSE support** | Yes — uses `.NS` suffix (e.g., `RELIANCE.NS`) |
| **Cost** | Free tier: 100 requests/day, 3 articles/request. Paid plans from $29/mo |
| **Toggle** | `USE_MARKETAUX=true/false` in `.env` (default: false) |

### How it works

When enabled, MarketAux data is fetched per-signal during the Multi-LLM Panel step and injected into the SENTIMENT agent's prompt as an additional data section alongside existing RSS headlines and keyword-based scoring.

```
SENTIMENT agent receives:
  1. Structured Sentiment Report   (existing - keyword scoring)
  2. Raw Recent News               (existing - RSS headlines)
  3. MarketAux API Sentiment       (NEW - entity-scored, -1.0 to +1.0)
  4. Analysis Context              (existing)
```

### Caching

Per-symbol per-day DB cache (`marketaux_cache` table) — re-runs on the same day use cached results with zero API calls. Only signals reaching the LLM panel trigger MarketAux calls (typically 5-30 stocks, not the full 1800-stock universe).

### Setup

```env
USE_MARKETAUX=true
MARKETAUX_API_KEY=your_token_here   # get from https://www.marketaux.com/account/dashboard
# MARKETAUX_MAX_ARTICLES=3          # articles per request (free tier max: 3)
# MARKETAUX_RATE_DELAY=0.5          # seconds between API calls
```

---

## Gemini Sentiment Validation

Optional post-panel validation step using Gemini 2.5 Flash with Google Search grounding. Runs **after** the multi-LLM panel (Step 4b), only on CONFIRM/WEAK signals. Gemini searches the web for the latest news about each stock, gives its own verdict, and can override the panel verdict.

| Setting | Value |
|---|---|
| **Provider** | Google Gemini |
| **Model** | `gemini-2.5-flash` (default) |
| **Method** | Google Search grounding — Gemini auto-searches, returns text + source citations |
| **Cost** | Free tier: 500 grounded searches/day, 10 RPM. Paid: $35 per 1,000 after free tier |
| **Toggle** | `USE_GEMINI_SENTIMENT=true/false` in `.env` (default: false) |
| **Step** | 4b (runs after panel, before Claude live validation) |

### How it works

When enabled, Gemini searches Google for the latest news (last 48 hours) about each CONFIRM/WEAK signal's stock, assesses sentiment (BULLISH/BEARISH/NEUTRAL with confidence 1-10), and returns article citations. The sentiment is mapped to a verdict (BULLISH→CONFIRM, BEARISH→REJECT, NEUTRAL→WEAK) and applied via an override table:

```
Panel Verdict | Gemini Verdict | Final Result
──────────────┼────────────────┼─────────────
CONFIRM       | CONFIRM        | CONFIRM   (double confirmed)
CONFIRM       | WEAK           | WEAK      (Gemini lacks conviction)
CONFIRM       | REJECT         | WEAK      (red flag found, downgrade)
WEAK          | CONFIRM        | CONFIRM   (Gemini upgrades)
WEAK          | WEAK           | WEAK      (no change)
WEAK          | REJECT         | REJECT    (both negative)
```

### Pipeline position

```
Step 4:  Multi-LLM Panel (Groq)  → panel verdict
Step 4b: Gemini Validation       → can override panel verdict (free, 500/day)
Step 4c: Claude Live Validation  → can override current verdict (paid, $10/1K searches)
Step 5:  Display & auto-enter
```

Gemini runs first (free) to filter signals before Claude (paid) validates survivors.

### Caching

Per-symbol per-day DB cache (`gemini_sentiment_cache` table) — re-runs on the same day use cached results with zero API calls. Gemini verdict also persisted to `breakout_log` (`gemini_verdict`, `gemini_confidence`, `gemini_reasoning` columns).

### Setup

```bash
pip install google-genai
```

```env
USE_GEMINI_SENTIMENT=true
GEMINI_SENTIMENT_API_KEY=your_key_here   # get from https://aistudio.google.com/apikey
# GEMINI_SENTIMENT_MODEL=gemini-2.5-flash
# GEMINI_SENTIMENT_RATE_DELAY=1.0
```

---

## Database Schema

### `instruments`
Master symbol reference table (symbol, instrument_key, instrument_name).

### `ohlcv`
OHLCV price cache (primary key: symbol + date). Foreign key to instruments.

### `breakout_log` -- date-wise signal history

| Column | Type | Description |
|---|---|---|
| `scan_date` | TEXT | Date the signal was detected |
| `symbol` | TEXT | NSE trading symbol |
| `signal_type` | TEXT | BREAKOUT or PULLBACK |
| `close`, `rsi`, `vol_ratio`, `score` | REAL/INT | Signal metrics |
| `stage` | TEXT | Stage1 / Stage2 / Stage3 |
| `ema20`, `ema50`, `atr14`, `swing_low` | REAL | Technical levels |
| `reasons` | TEXT | Screener rule triggers |
| `llm_verdict` | TEXT | Final verdict: CONFIRM / WEAK / REJECT / SKIPPED |
| `llm_confidence` | INT | 1-10 |
| `llm_reasoning` | TEXT | Final reasoning (from panel or debate moderator) |
| `tech_verdict`, `tech_confidence`, `tech_reasoning` | TEXT/INT | Technical agent output |
| `sent_verdict`, `sent_confidence`, `sent_reasoning` | TEXT/INT | Sentiment agent output |
| `risk_verdict`, `risk_confidence`, `risk_reasoning` | TEXT/INT | Risk agent output |
| `debate_triggered` | INT | 1 if debate was triggered, 0 otherwise |
| `debate_winner` | TEXT | BULL / BEAR / DRAW |
| `debate_reasoning` | TEXT | Moderator's reasoning |
| `panel_method` | TEXT | MULTI_LLM / SINGLE_LLM |
| `weighted_score` | REAL | Consensus score (0.0 to 1.0) |
| `vcp_detected` | INT | 1 if VCP pattern found |
| `bull_flag_detected` | INT | 1 if Bull Flag found |
| `pattern_score` | INT | Bonus points from patterns |
| `live_verdict`, `live_confidence`, `live_reasoning` | TEXT/INT | Claude live validation output |

UNIQUE constraint: `(scan_date, symbol)` -- one entry per symbol per day.

### `positions`
Open and closed paper-trade positions with buy price, target, SL, trailing stop, exit details, and PnL %.

### `signals`
Log of every BUY/SELL signal with date, price, and reason.

### `news_cache`
RSS article cache (title, URL, published date, source, body).

### `marketaux_cache`
Per-symbol per-day cache for MarketAux API responses (`symbol + scan_date` unique key, `response_json`).

### `gemini_sentiment_cache`
Per-symbol per-day cache for Gemini grounded news sentiment (`symbol + scan_date` unique key, `response_json`).

---

## Configuration

All settings live in `config.py` and can be overridden via environment variables or a `.env` file.

### Core Settings

```python
# --- Upstox ---
UPSTOX_ACCESS_TOKEN  # Upstox OAuth2 bearer token (required for data)

# --- Screener ---
LOOKBACK_DAYS       = 365     # OHLCV history to fetch per symbol
VOLUME_SURGE_FACTOR = 1.5     # minimum volume ratio for plain surge
RSI_BREAKOUT_MIN    = 55      # RSI lower bound for momentum zone
RSI_OVERBOUGHT      = 75      # RSI upper bound (skip overbought)
MIN_PRICE           = 20      # exclude stocks below Rs.20
MAX_PRICE           = 5000    # exclude stocks above Rs.5000

# --- Risk Management ---
PROFIT_TARGET_PCT   = 10.0    # flat ceiling exit %
STOP_LOSS_PCT       = 5.0     # fallback SL % (when ATR unavailable)
MAX_HOLD_DAYS       = 21      # max position hold in days
MAX_OPEN_POSITIONS  = 10      # max simultaneous open positions
ATR_SL_MULTIPLIER   = 1.5     # initial SL = price - 1.5 x ATR14
ATR_TRAIL_MULTIPLIER= 1.5     # trailing stop = current - 1.5 x ATR14

# --- Scheduler ---
SCAN_TIME_IST       = "09:20" # 20 min after NSE open
```

### LLM Panel Settings

```env
# Provider (groq / ollama / openai / openrouter / gemini)
LLM_PROVIDER=groq
LLM_API_KEY=gsk_your_groq_key_here
LLM_BASE_URL=https://api.groq.com/openai/v1

# Panel agent models (Groq paid subscription)
LLM_PANEL_TECH_MODEL=meta-llama/llama-4-scout-17b-16e-instruct
LLM_PANEL_SENT_MODEL=llama-3.1-8b-instant
LLM_PANEL_RISK_MODEL=meta-llama/llama-4-scout-17b-16e-instruct
LLM_PANEL_MODERATOR_MODEL=meta-llama/llama-4-maverick-17b-128e-instruct

# Panel behaviour
USE_MULTI_LLM_PANEL=true         # true = multi-agent panel, false = single-LLM
LLM_PANEL_MAX_TOKENS=512
LLM_TEMPERATURE=0.2

# Rate-limit mitigation
PANEL_SEQUENTIAL_MODE=false       # true = run agents one-at-a-time
PANEL_AGENT_DELAY=1.0             # seconds between agents in sequential mode

# Live Validation (optional)
USE_LIVE_VALIDATION=true
LIVE_API_KEY=sk-ant-your_key_here  # https://console.anthropic.com/settings/keys
LIVE_MODEL=claude-opus-4-6

# MarketAux News/Sentiment (optional, pluggable)
USE_MARKETAUX=true
MARKETAUX_API_KEY=your_token_here  # https://www.marketaux.com/account/dashboard
MARKETAUX_MAX_ARTICLES=3           # free tier max
MARKETAUX_RATE_DELAY=0.5           # seconds between API calls

# Gemini Sentiment Validation (optional, post-panel step 4b)
USE_GEMINI_SENTIMENT=true
GEMINI_SENTIMENT_API_KEY=your_key  # https://aistudio.google.com/apikey
GEMINI_SENTIMENT_MODEL=gemini-2.5-flash
GEMINI_SENTIMENT_RATE_DELAY=1.0    # seconds between API calls
```

### Free-Tier Fallback Models

If you don't have a paid Groq subscription:

```env
LLM_PANEL_TECH_MODEL=llama-3.3-70b-versatile
LLM_PANEL_SENT_MODEL=llama-3.1-8b-instant
LLM_PANEL_RISK_MODEL=meta-llama/llama-4-scout-17b-16e-instruct
LLM_PANEL_MODERATOR_MODEL=llama-3.3-70b-versatile
```

---

## Setup & Installation

### 1. Clone / open the project

```bash
cd nse_breakout_agent
```

### 2. Create a virtual environment

```bash
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Create a `.env` file

```env
# Upstox (required) -- generate token at https://upstox.com/developer/
UPSTOX_ACCESS_TOKEN=your_upstox_token_here

# Groq (required for LLM panel) -- https://console.groq.com/keys
LLM_API_KEY=gsk_your_key_here
LLM_PROVIDER=groq

# Panel models (paid Groq subscription)
LLM_PANEL_TECH_MODEL=meta-llama/llama-4-scout-17b-16e-instruct
LLM_PANEL_SENT_MODEL=llama-3.1-8b-instant
LLM_PANEL_RISK_MODEL=meta-llama/llama-4-scout-17b-16e-instruct
LLM_PANEL_MODERATOR_MODEL=meta-llama/llama-4-maverick-17b-128e-instruct

# Live Validation (optional)
USE_LIVE_VALIDATION=true
LIVE_API_KEY=sk-ant-your_key_here    # https://console.anthropic.com/settings/keys
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

# Force re-download all OHLCV data (bypass cache)
python main.py scan --force-refresh

# Scan against a specific past date (auto-routes to backtest if past date)
python main.py scan --date 2026-02-27

# View current open portfolio
python main.py portfolio

# View date-wise breakout history (last 30 days)
python main.py log

# View last 7 days only
python main.py log --days 7

# Run as a scheduled daemon (auto-runs at 09:20 IST Mon-Fri)
python main.py schedule

# Backtesting -- validate signals from a past date
python main.py backtest --date 2026-02-01
python main.py backtest --date 2026-02-01 --days 15
```

### Sample Scan Output

```
============================================================
   NSE BREAKOUT AGENT - DAILY SCAN
============================================================
   Scan date : 2026-02-28

[1/5] Checking exit conditions...
  No exits triggered.

[2/5] Fetching market news...
  12 new articles cached.

[3/5] Loading NSE EQ universe...
  Universe: 1847 NSE EQ instruments.
  Done. Downloaded: 43 | From cache: 1798 | Skipped (open pos): 6

[4/5] Multi-LLM Panel (5 signal(s))...
      TECHNICAL : meta-llama/llama-4-scout-17b-16e-instruct
      SENTIMENT : llama-3.1-8b-instant
      RISK      : meta-llama/llama-4-scout-17b-16e-instruct
      MODERATOR : meta-llama/llama-4-maverick-17b-128e-instruct
  [Panel 1/5] RELIANCE       -> CONFIRM conf=8/10 | TECH:CONFIRM(8) SENT:CONFIRM(7) RISK:CONFIRM(8)
  [Panel 2/5] HDFCBANK       -> WEAK    conf=5/10 | TECH:CONFIRM(7) SENT:WEAK(5) RISK:WEAK(4) | DEBATE->BEAR
  [Panel 3/5] TATAMOTORS     -> CONFIRM conf=9/10 | TECH:CONFIRM(9) SENT:CONFIRM(8) RISK:CONFIRM(7)
  ...

[4b/5] Live validation (3 signal(s))...
       Claude + Web Search
  ...

[5/5] Results: 5 breakout candidate(s) found.
  CONFIRM : 3  |  WEAK : 1  |  REJECT : 1

==============================================================
  *  TODAY'S TOP PICKS  -  2026-02-28  *
  (Stage2 | LLM CONFIRM | Score>=10 | Vol>=1.8x | RSI<=70)
==============================================================
  #1  RELIANCE     Rs.1284.50  Score:16  RSI:63  Vol:2.4x  LLM:CONFIRM(8/10) [VCP]
      Entry Rs.1284.50  ->  Target Rs.1345.78  ->  SL Rs.1253.86  (Risk 2.4% | 2R reward)
      Agents: TECH:CONFIRM(8/10) SENT:CONFIRM(7/10) RISK:CONFIRM(8/10)
```

---

## Backtesting & Validation

The backtest command replays the screener on any past date using **only data already in your local SQLite DB** (no API calls, no future leakage), then validates each signal against real forward price action.

### How It Works

```
1. All symbols cached in the DB with data on or before <signal_date> are loaded.
2. Each symbol's history is CAPPED at signal_date (no future data used).
3. The same breakout + pullback scanners run on the capped data.
4. SL and 2R target are calculated with the exact same logic as the live screener.
5. Forward candles (signal_date+1 to signal_date+N) are loaded from the DB.
6. Each forward day is walked:
     intraday HIGH >= 2R target  ->  WIN   (recorded on that day)
     intraday LOW  <= stop loss  ->  LOSS  (recorded on that day)
     neither in N days           ->  OPEN
7. Stats: max gain %, max drawdown %, final close % are recorded per signal.
```

### Key Definitions

| Term | Definition |
|---|---|
| **WIN** | Intraday high reached the 2R target before stop loss was hit |
| **LOSS** | Intraday low hit or broke through the stop loss before target |
| **OPEN** | Neither triggered within the forward window |
| **Max Gain %** | Best intraday high vs entry price across all forward candles |
| **Max DD %** | Worst intraday low vs entry price (negative = drawdown below entry) |
| **Expectancy** | `(win_rate x avg_max_gain) + ((1-win_rate) x avg_max_dd)` |

> **Note:** The backtest does not run LLM validation (would require API calls for historical dates).
> All outcomes are determined purely from cached local OHLCV data.

---

## Risk Management

The agent uses a layered exit strategy applied in priority order on every portfolio check:

```
1. STORED TARGET HIT   -> exit when price >= calculated 2R target (ATR-based)
2. PROFIT TARGET %     -> fallback ceiling at +10% (configurable)
3. TRAILING STOP       -> current_price - 1.5 x ATR14, ratcheted UP only (never down)
4. MAX HOLD DAYS       -> forced exit after 21 days regardless of PnL
```

**Stop loss calculation at entry:**
```
SL_atr   = buy_price - 1.5 x ATR14
SL_swing = swing_low x 0.99          (most recent local trough)
SL       = max(SL_atr, SL_swing)     <- tightest valid stop above zero
```

**Target calculation at entry:**
```
risk     = buy_price - SL
target   = buy_price + (risk x 2)    <- 2R reward-to-risk ratio
```

---

## Data Flow

```
Upstox API
    |  GET /v2/historical-candle/{instrument_key}/day/{to}/{from}
    v
upstox_client.py   --> instruments JSON (NSE.json.gz) -> symbol-key map
    |
    v
database.py        --> ohlcv table  (cache; keyed by symbol+date)
    |
    v
technical.py       --> EMA20/50/200, RSI, MACD, Bollinger, ATR14,
                       Volume ratio, Supertrend, 20d high, 52w high/low
    |
    v
breakout_scanner.py -> score-based breakout signal  OR  pullback signal
    |
    v
pattern_scanner.py --> VCP + Bull Flag detection -> bonus score
    |
    v
news_fetcher.py    --> merge recent headlines into signal dict
sentiment_scorer.py -> structured sentiment report (no LLM)
marketaux_client.py -> [optional] API-scored entity sentiment (MarketAux)
    |
    v
llm_panel.py       --> 3 agents in parallel (TECH + SENT + RISK)
                   --> weighted consensus + auto-debate if needed
                   --> panel verdict: CONFIRM / WEAK / REJECT
    |
    v
gemini_sentiment.py -> [Step 4b, optional] Gemini + Google Search (free)
                   --> post-panel validation, override table
    |
    v
live_validator.py  --> [Step 4c, optional] Claude + web search (paid)
                   --> post-panel validation, override table
    |
    v
database.py        --> save_breakout_log()   (breakout_log table)
                   --> open_position()       (positions table)
                   --> save_signal()         (signals table)
    |
    v
html_report_writer.py --> reports/Scan-YYYY-MM-DD.html
```
