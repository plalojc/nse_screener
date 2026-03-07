# NSE Breakout Agent

An automated stock screener for NSE (India) equities that detects breakout and pullback setups, validates signals through a multi-LLM panel with bull/bear debate (or a single Gemini + Google Search call), manages a paper-trade portfolio with ATR-based stops, and keeps a full date-wise history of every signal.

---

## Table of Contents

- [Features](#features)
- [Project Structure](#project-structure)
- [Architecture](#architecture)
- [Validation Paths](#validation-paths)
  - [Option A — Gemini Direct Validator (Recommended)](#option-a--gemini-direct-validator-recommended)
  - [Option B — Multi-LLM Panel + Groq](#option-b--multi-llm-panel--groq)
- [Signal Detection Logic](#signal-detection-logic)
- [Advanced Pattern Detection](#advanced-pattern-detection)
- [Gemini Sentiment Validation](#gemini-sentiment-validation)
- [Live Validation (Claude)](#live-validation-claude)
- [MarketAux Integration](#marketaux-integration)
- [ETF & Invalid Instrument Filtering](#etf--invalid-instrument-filtering)
- [Upstox OAuth](#upstox-oauth)
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
| **ETF filtering** | 3-layer ETF detection; permanently blacklists ETFs and no-data symbols in `invalid_instruments` table |
| **Two signal types** | Momentum Breakout + MA Pullback (buy-the-dip) |
| **Scoring engine** | 9-criteria weighted score (max ~20); threshold >= 7 to emit a signal |
| **Gemini Direct Validator** | Recommended path: single Gemini 2.5 Flash call + Google Search — replaces the entire 4-agent panel with 1 live-news-aware call |
| **Multi-LLM Panel** | Alternative: 3-agent ensemble (Technical, Sentiment, Risk) with weighted consensus + bull/bear debate (Groq) |
| **Advanced Patterns** | VCP (Minervini) and Bull Flag detection with bonus scoring |
| **Sentiment Analysis** | News RSS + structured sentiment scoring before LLM call |
| **MarketAux Integration** | Optional pluggable news source with API-scored entity sentiment for NSE stocks |
| **Gemini Sentiment Validation** | Optional post-panel validation via Gemini 2.5 Flash + Google Search grounding (Step 4b) |
| **Live Validation** | Optional post-panel validation via Claude Opus 4.6 + web search for real-time news check (Step 4c) |
| **SQLite cache** | OHLCV data cached; only fetches fresh data for symbols without up-to-date history |
| **ATR-based risk** | Initial SL = close - 1.5 × ATR14, ratcheted trailing stop updated every scan |
| **Portfolio tracker** | Tracks open positions; exits on profit target, trailing stop, or max hold days |
| **Breakout log** | Date-wise history of every signal + per-agent verdicts stored in SQLite |
| **HTML Reports** | Full-colour HTML report generated after every scan and every backtest run |
| **Backtesting** | Re-run screener on any past date using cached DB data; validate against real forward price action |
| **Rate-limit hardening** | Exponential backoff (1-2-4-8s) for 429 errors + optional sequential agent mode |
| **Upstox OAuth** | One-command token refresh via local browser callback (`python main.py auth`) |
| **Scheduler** | APScheduler cron job runs automatically at 08:20 IST Mon-Fri |

---

## Project Structure

```
nse_breakout_agent/
|
|-- main.py                  # CLI entry point (scan, portfolio, log, backtest, schedule, auth, clear-log)
|-- config.py                # All settings (API keys, thresholds, LLM models, panel weights)
|-- scheduler.py             # APScheduler daily cron runner (08:20 IST)
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
|   |-- gemini_validator.py  # Gemini Direct Validator (recommended; replaces panel + 4b + 4c)
|   |-- llm_panel.py         # Multi-LLM panel: 3 agents + debate + consensus (Groq)
|   |-- llm_validator.py     # Single-LLM fallback validator (Groq/OpenAI/Ollama)
|   |-- marketaux_client.py  # MarketAux.com API client (pluggable news sentiment)
|   |-- gemini_sentiment.py  # Post-panel: Gemini 2.5 Flash + Google Search validation (Step 4b)
|   |-- live_validator.py    # Post-panel: Claude Opus 4.6 + web search validation (Step 4c)
|   |-- backtester.py        # Past-date signal replay + forward outcome evaluation
|
|-- auth/
|   |-- upstox_auth.py       # Upstox OAuth2 token refresh (local browser callback)
|
|-- data/
|   |-- upstox_client.py     # Upstox v2 REST API client (historical OHLCV + ETF filter)
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
              (CLI: scan | portfolio | log | backtest | auth | clear-log)
                               |
                               v
                      screener_agent.py
    ============================================================
    Step 1  Check exit conditions on open positions
    Step 2  Fetch & cache market news (RSS)
    Step 3  Scan NSE EQ universe (~1800 symbols)
              - Filter ETFs & invalid instruments (blacklist)
              - Load from SQLite cache if fresh
              - Else fetch from Upstox API
              - Run breakout_scanner + pattern_scanner
    Step 4  LLM Validation (per signal) — choose ONE path:
              ┌─────────────────────────────────────────────────┐
              │ Path A (Recommended): USE_GEMINI_VALIDATOR=true  │
              │   gemini_validator.py (1 call, Google Search)   │
              │   → Steps 4b & 4c are SKIPPED (redundant)       │
              ├─────────────────────────────────────────────────┤
              │ Path B: USE_MULTI_LLM_PANEL=true (Groq)         │
              │   llm_panel.py (3-agent + debate)               │
              │   → [4b] Gemini Sentiment (optional)            │
              │   → [4c] Claude Live Validation (optional)      │
              ├─────────────────────────────────────────────────┤
              │ Path C: Single-LLM fallback (llm_validator.py)  │
              └─────────────────────────────────────────────────┘
    Step 5  Display results + auto-enter Stage2 positions
              +-- HTML report generation
    ============================================================
              |                  |                  |
              v                  v                  v
       +------------+    +-------------+    +--------------+
       | Upstox v2  |    |  pandas-ta  |    | Groq / Gemini|
       | REST API   |    |  indicators |    | / Anthropic  |
       | (OHLCV)    |    |             |    |              |
       +-----+------+    +------+------+    +------+-------+
             |                  |                  |
             +------------------+------------------+
                               |
                               v
                    +---------------------+
                    |     SQLite DB       |
                    |  - instruments      |
                    |  - invalid_instruments (blacklist)
                    |  - ohlcv            |
                    |  - breakout_log     |
                    |  - positions        |
                    |  - signals          |
                    |  - news_cache       |
                    |  - marketaux_cache  |
                    |  - gemini_sentiment_cache
                    +---------------------+
```

---

## Validation Paths

### Option A — Gemini Direct Validator (Recommended)

**Set `USE_GEMINI_VALIDATOR=true` in `.env`**

One Gemini 2.5 Flash call per signal with Google Search grounding. This is the recommended path for most users.

| | Multi-LLM Panel (Path B) | Gemini Direct (Path A) |
|---|---|---|
| API calls per signal | 4–6 (3 agents + debate + moderator) | 1 |
| Live web search | No (static context only) | Yes (Google Search grounding) |
| Cost | Groq tokens | Gemini tokens + search |
| Latency | ~15–30s | ~5–10s |
| Reasoning coherence | Multiple agents, may disagree | Single coherent reasoning |
| Free tier | Yes (Groq free tier) | Yes (10 RPM free) |

When `USE_GEMINI_VALIDATOR=true`:
- The multi-LLM panel (Step 4) is replaced entirely
- Steps 4b (Gemini Sentiment) and 4c (Claude Live) are automatically **skipped** — they are redundant duplicates
- Gemini searches Google in real time for news, orders, earnings, SEBI notices

```env
USE_GEMINI_VALIDATOR=true
GEMINI_VALIDATOR_API_KEY=your_key_here   # https://aistudio.google.com/apikey
# GEMINI_VALIDATOR_MODEL=gemini-2.5-flash       # default
# GEMINI_VALIDATOR_RATE_DELAY=6.0               # free tier: 10 RPM → 6s between calls
# GEMINI_VALIDATOR_CONCURRENCY=10               # max concurrent calls in flight
```

**Free-tier rate limits:**
- Free: 10 RPM → set `GEMINI_VALIDATOR_RATE_DELAY=6.0` (default)
- Paid Tier 1: 150 RPM → set `GEMINI_VALIDATOR_RATE_DELAY=0.4` and `GEMINI_VALIDATOR_CONCURRENCY=20`

---

### Option B — Multi-LLM Panel + Groq

The 3-agent ensemble with weighted consensus and automated debate, inspired by TradingAgents (2024–2025) research. Use this when you want full control over per-agent reasoning and want to mix Gemini/Claude as post-panel validators.

#### Model Assignment (Groq)

| Role | Model | Why |
|---|---|---|
| **TECHNICAL Analyst** | `llama-4-scout` | Fast, math/logic focused, chart pattern analysis |
| **SENTIMENT Analyst** | `llama-3.1-8b-instant` | Quick NLP, news categorization as positive/negative |
| **RISK Manager** | `llama-4-scout` | Stop loss quality, R:R assessment, tail risk analysis |
| **Bull Debater** | `llama-4-scout` | Argues FOR the trade with specific data points |
| **Bear Debater** | `llama-4-scout` | Argues AGAINST the trade, identifies risks |
| **MODERATOR** | `llama-4-maverick` | Reads all inputs, makes final CONFIRM/REJECT decision |

#### How It Works

```
Step 1: Pre-compute (no LLM)
    - Pattern scan (VCP, Bull Flag) -> bonus score
    - News fetch + sentiment scoring -> structured report
    - Open position count -> risk context

Step 2: 3 Agents in Parallel (or sequential mode)
    +-- TECHNICAL (Scout) -> verdict + confidence + reasoning
    +-- SENTIMENT (8b)    -> verdict + confidence + reasoning
    +-- RISK      (Scout) -> verdict + confidence + reasoning

Step 3: Weighted Consensus
    Score = TECH×0.50 + SENT×0.20 + RISK×0.30   (configurable via .env)
    CONFIRM >= 0.65 | WEAK >= 0.42 | else REJECT

Step 4: Debate (auto-triggered when needed)
    Triggers when:
      - TECHNICAL=CONFIRM and SENTIMENT=REJECT (fundamental conflict)
      - Any CONFIRM and RISK=REJECT (risk veto)
      - Weighted score in grey zone [0.42, 0.65]
      - NOT triggered: sole CONFIRM + 2 WEAKs (no real disagreement → outputs WEAK directly)

    Turn 1: Bull Researcher (Scout) argues FOR
    Turn 2: Bear Researcher (Scout) argues AGAINST
    Turn 3: Fund Manager (Maverick) makes final call
                -> overrides weighted consensus

Step 5: Final Verdict
    If debate triggered -> use Moderator's verdict
    Else -> use weighted consensus verdict
```

#### Consensus Weight Rationale

Default weights are calibrated for NSE mid/small-cap stocks where RSS feeds typically yield 0–2 headlines per symbol. Based on FinAgent (arXiv 2402.18679) and TradingAgents (arXiv 2412.20138) research:

| Agent | Weight | Rationale |
|---|---|---|
| TECHNICAL | 0.50 | Primary signal; chart data is always present and objective |
| RISK | 0.30 | Stop quality and R:R are critical for trade safety |
| SENTIMENT | 0.20 | Downweighted vs old 0.35 because RSS data is sparse for most NSE stocks |

Increase `PANEL_SENT_WEIGHT` if MarketAux (`USE_MARKETAUX=true`) or Gemini (`USE_GEMINI_SENTIMENT=true`) are providing richer news data.

#### Fallback Chain

```
Multi-LLM Panel fails -> Single-LLM fallback (llm_validator.py)
Single-LLM fails     -> verdict = SKIPPED
```

#### Rate-Limit Hardening

- **Exponential backoff**: `_call_llm()` retries up to 4 times on HTTP 429 errors (waits 1s, 2s, 4s, 8s)
- **Sequential mode**: Set `PANEL_SEQUENTIAL_MODE=true` to run agents one-at-a-time with configurable delay
- **Verdict cache**: Re-running scan on the same day uses cached verdicts (zero API calls)

---

## Signal Detection Logic

### Breakout Scanner (`is_breakout`)

Nine scoring criteria — minimum score of **7** required to emit a signal:

| # | Criterion | Points |
|---|---|---|
| 1 | 20-day high breakout **+** volume >= 2x average | +3 |
| | Plain volume surge >= 1.5x average (without price breakout) | +1 |
| 2 | RSI 55–80 (momentum zone, not overbought) | +2 |
| 3 | Close > EMA20 > EMA50 (trend alignment) | +2 |
| 4 | MACD histogram bullish crossover | +2 |
| | MACD crossover while MACD line still negative (high-potential early entry) | +4 |
| 5 | Close >= Bollinger Band upper | +2 |
| 6 | Within 3% of 52-week high | +3 |
| 7 | EMA20/50 golden cross in last 5 days | +3 |
| 8 | Supertrend fresh flip to bullish | +3 |
| | Supertrend already bullish (confirmation) | +1 |
| 9 | Close > EMA200 (macro uptrend filter) | +1 |

**Signal dict fields** (subset, all returned by `is_breakout` and `is_ma_pullback`):

```python
{
  "symbol":        str,      # NSE trading symbol
  "signal_type":   str,      # "BREAKOUT" or "PULLBACK"
  "close":         float,    # current close price
  "rsi":           float,    # RSI-14
  "vol_ratio":     float,    # current volume / 20-day avg volume
  "score":         int,      # multi-factor score
  "stage":         str,      # "Stage1" / "Stage2" / "Stage3"
  "ema20":         float,
  "ema50":         float,
  "ema200":        float,    # macro trend level (None if < 200 bars)
  "atr14":         float,    # ATR-14 for stop calculation
  "swing_low":     float,    # most recent local trough
  "macd_hist":     float,    # MACD histogram (positive = bullish momentum)
  "supertrend_dir":int,      # 1 = BULLISH, -1 = BEARISH, None = N/A
  "reasons":       str,      # comma-separated rule triggers
}
```

### MA Pullback Scanner (`is_ma_pullback`)

All four conditions must be true (pass/fail, no scoring):

1. EMA50 > EMA200 — macro uptrend confirmed
2. Candle low <= EMA50 — price dipped to the 50 EMA
3. Candle close > EMA50 — buyers defended the level
4. RSI < 45 — short-term oversold

---

## Advanced Pattern Detection

The pattern scanner (`analysis/pattern_scanner.py`) adds bonus scoring to signals:

### VCP (Volatility Contraction Pattern — Minervini)

Detects progressively tightening price contractions before a breakout. Requires >= 65 bars of data. Adds **+2 to +4 bonus points** when detected (higher for more contractions or stronger breakout volume).

### Bull Flag

Detects a strong impulse move (pole) followed by a tight consolidation channel (flag). Requires >= 25 bars. Adds **+1 to +3 bonus points** when detected.

Both patterns appear as badges in the Top Picks display:
```
#1  RELIANCE     ₹1284.50  Score:16  RSI:63  Vol:2.4x  LLM:CONFIRM(8/10) [VCP] [FLAG]
```

---

## Gemini Sentiment Validation

**Only active in the Multi-LLM Panel path (Path B). Automatically skipped when `USE_GEMINI_VALIDATOR=true`.**

Optional post-panel validation step using Gemini 2.5 Flash with Google Search grounding. Runs **after** the multi-LLM panel (Step 4b), only on CONFIRM/WEAK signals. Acts as a protective filter.

| Setting | Value |
|---|---|
| **Provider** | Google Gemini |
| **Model** | `gemini-2.5-flash` (default) |
| **Method** | Google Search grounding — 6-dimension analysis (news, orders, earnings, geopolitics, supply/demand, peer contagion) |
| **Cost** | Free tier: 500 grounded searches/day, 10 RPM |
| **Toggle** | `USE_GEMINI_SENTIMENT=true/false` in `.env` (default: false) |
| **Step** | 4b (runs after panel, before Claude live validation) |

### Override Logic (Protective Only)

Gemini can **downgrade** signals but can **never upgrade** a WEAK to CONFIRM. Only Claude (Step 4c) has upgrade authority.

```
Panel Verdict | Gemini Verdict | Final Result
──────────────┼────────────────┼─────────────
CONFIRM       | CONFIRM        | CONFIRM   (news supports)
CONFIRM       | WEAK           | CONFIRM   (neutral news doesn't invalidate technicals)
CONFIRM       | REJECT         | WEAK      (bad news found → downgrade)
WEAK          | CONFIRM        | WEAK      (good news can't fix technical/risk issues)
WEAK          | WEAK           | WEAK      (no change)
WEAK          | REJECT         | REJECT    (bad news confirms weakness)
```

### Setup

```bash
pip install google-genai
```

```env
USE_GEMINI_SENTIMENT=true
GEMINI_SENTIMENT_API_KEY=your_key_here   # https://aistudio.google.com/apikey
# GEMINI_SENTIMENT_MODEL=gemini-2.5-flash
# GEMINI_SENTIMENT_RATE_DELAY=1.0
```

---

## Live Validation (Claude)

**Only active in the Multi-LLM Panel path (Path B). Automatically skipped when `USE_GEMINI_VALIDATOR=true`.**

Optional final-pass validation using Claude Opus 4.6 with server-side web search (Step 4c). Claude is the **final arbiter** — it can both upgrade and downgrade the verdict.

| Setting | Value |
|---|---|
| **Provider** | Anthropic (Claude) |
| **Model** | `claude-opus-4-6` (default) |
| **Method** | Server-side web search (`web_search_20250305`) — Claude searches the web automatically and cites sources |
| **Cost** | $10 per 1,000 web searches + standard token costs |
| **Triggers on** | CONFIRM and WEAK signals only (skips REJECTs to save quota) |
| **Max searches** | 3 per signal |

### Authority Hierarchy (Panel path only)

```
Step 4:  Multi-LLM Panel (Groq)  → primary verdict (3-agent ensemble)
Step 4b: Gemini Validation       → protective filter (free, can only DOWNGRADE)
Step 4c: Claude Live Validation  → final arbiter (paid, can both UP/DOWNGRADE)
```

### Override Logic

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
LIVE_API_KEY=sk-ant-your_key_here    # https://console.anthropic.com/settings/keys
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

When enabled, MarketAux data is fetched per-signal and injected into the SENTIMENT agent's prompt alongside existing RSS headlines:

```
SENTIMENT agent receives:
  1. Structured Sentiment Report   (existing - keyword scoring)
  2. Raw Recent News               (existing - RSS headlines)
  3. MarketAux API Sentiment       (optional - entity-scored, -1.0 to +1.0)
```

Per-symbol per-day DB cache (`marketaux_cache` table) prevents duplicate API calls on same-day re-runs.

```env
USE_MARKETAUX=true
MARKETAUX_API_KEY=your_token_here   # https://www.marketaux.com/account/dashboard
# MARKETAUX_MAX_ARTICLES=3
# MARKETAUX_RATE_DELAY=0.5
```

---

## ETF & Invalid Instrument Filtering

The screener automatically excludes ETFs, index funds, and symbols that never return data.

### 3-Layer ETF Detection (in `upstox_client.py`)

1. **Name keywords**: instrument name contains "ETF", "Index Fund", "BEES", "FoF", etc.
2. **Symbol patterns**: ends in `BEES`, `NIFTY`, `GOLD`, `LIQUID`, etc.
3. **Instrument type**: Upstox API field `instrument_type != "EQ"`

### Persistent Blacklist (`invalid_instruments` table)

Symbols that fail ETF checks, or that never return OHLCV data from Upstox (delisted/suspended), are written to the `invalid_instruments` SQLite table and permanently skipped on all future scans — **no API call is made for them**.

This table is also used to skip symbols pre-emptively before entering the download loop, cutting the scan universe from ~1800 to the effective tradeable subset.

```sql
-- Table structure
CREATE TABLE invalid_instruments (
    symbol      TEXT PRIMARY KEY,
    reason      TEXT,   -- e.g. "ETF", "NO_DATA"
    source      TEXT,   -- e.g. "UPSTOX_FILTER", "SCAN_EMPTY"
    added_at    TEXT
);
```

**Toggle ETF filtering:**
```env
FILTER_ETFS=true   # default: true — set false to include ETFs in universe
```

---

## Upstox OAuth

The Upstox API requires an OAuth2 access token that typically expires daily. The agent includes a one-command token refresh flow.

### `python main.py auth`

1. Opens the Upstox login URL in your default browser
2. Starts a local HTTP server on port 8080 to capture the OAuth callback
3. Exchanges the authorization code for a fresh access token
4. Writes `UPSTOX_ACCESS_TOKEN=<new_token>` to your `.env` file automatically

### Setup requirements

```env
UPSTOX_CLIENT_ID=your_client_id
UPSTOX_CLIENT_SECRET=your_client_secret
UPSTOX_REDIRECT_URI=http://127.0.0.1:8080/callback
```

Get `CLIENT_ID` and `CLIENT_SECRET` from the [Upstox Developer Portal](https://developer.upstox.com/).

---

## Database Schema

### `instruments`
Master symbol reference table (symbol, instrument_key, instrument_name).

### `invalid_instruments`
Permanent blacklist of ETFs and delisted/no-data symbols. Written automatically during scans. Pre-filters the universe to avoid wasted API calls.

### `ohlcv`
OHLCV price cache (primary key: symbol + date). Foreign key to instruments.

### `breakout_log` — date-wise signal history

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
| `llm_confidence` | INT | 1–10 |
| `llm_reasoning` | TEXT | Final reasoning (from panel, debate moderator, or Gemini Direct) |
| `tech_verdict`, `tech_confidence`, `tech_reasoning` | TEXT/INT | Technical agent output (panel path only) |
| `sent_verdict`, `sent_confidence`, `sent_reasoning` | TEXT/INT | Sentiment agent output (panel path only) |
| `risk_verdict`, `risk_confidence`, `risk_reasoning` | TEXT/INT | Risk agent output (panel path only) |
| `debate_triggered` | INT | 1 if debate was triggered, 0 otherwise |
| `debate_winner` | TEXT | BULL / BEAR / DRAW |
| `debate_reasoning` | TEXT | Moderator's reasoning |
| `panel_method` | TEXT | MULTI_LLM / SINGLE_LLM / GEMINI_DIRECT |
| `weighted_score` | REAL | Consensus score (0.0 to 1.0) |
| `vcp_detected` | INT | 1 if VCP pattern found |
| `bull_flag_detected` | INT | 1 if Bull Flag found |
| `pattern_score` | INT | Bonus points from patterns |
| `gemini_verdict`, `gemini_confidence`, `gemini_reasoning` | TEXT/INT | Gemini Sentiment output (Step 4b) |
| `live_verdict`, `live_confidence`, `live_reasoning` | TEXT/INT | Claude live validation output (Step 4c) |

UNIQUE constraint: `(scan_date, symbol)` — one entry per symbol per day.

### `positions`
Open and closed paper-trade positions with buy price, target, SL, trailing stop, exit details, and PnL %.

### `signals`
Log of every BUY/SELL signal with date, price, and reason.

### `news_cache`
RSS article cache (title, URL, published date, source, body).

### `marketaux_cache`
Per-symbol per-day cache for MarketAux API responses (`symbol + scan_date` unique key).

### `gemini_sentiment_cache`
Per-symbol per-day cache for Gemini grounded news sentiment (`symbol + scan_date` unique key).

---

## Configuration

All settings live in `config.py` and can be overridden via environment variables or a `.env` file.

### Core Settings

```python
# --- Upstox ---
UPSTOX_ACCESS_TOKEN   # Upstox OAuth2 bearer token (required for data)

# --- Screener ---
LOOKBACK_DAYS        = 365     # OHLCV history to fetch per symbol
VOLUME_SURGE_FACTOR  = 1.5     # minimum volume ratio for plain surge
RSI_BREAKOUT_MIN     = 55      # RSI lower bound for momentum zone
RSI_OVERBOUGHT       = 80      # RSI upper bound (skip overbought entries)
MIN_PRICE            = 20      # exclude stocks below Rs.20
MAX_PRICE            = 5000    # exclude stocks above Rs.5000
FILTER_ETFS          = true    # exclude ETFs/index funds from universe

# --- Risk Management ---
PROFIT_TARGET_PCT    = 10.0    # flat ceiling exit %
STOP_LOSS_PCT        = 5.0     # fallback SL % (when ATR unavailable)
MAX_HOLD_DAYS        = 21      # max position hold in days
MAX_OPEN_POSITIONS   = 10      # max simultaneous open positions
ATR_SL_MULTIPLIER    = 1.5     # initial SL = price - 1.5 × ATR14
ATR_TRAIL_MULTIPLIER = 1.5     # trailing stop = current - 1.5 × ATR14

# --- Scheduler ---
SCAN_TIME_IST        = "08:20" # 20 min after NSE open
```

### Validation Path — Gemini Direct (Recommended)

```env
USE_GEMINI_VALIDATOR=true
GEMINI_VALIDATOR_API_KEY=your_key_here       # https://aistudio.google.com/apikey
#                                              (can reuse GEMINI_SENTIMENT_API_KEY)
GEMINI_VALIDATOR_MODEL=gemini-2.5-flash      # or gemini-2.5-pro for higher accuracy
GEMINI_VALIDATOR_RATE_DELAY=6.0              # free tier: 10 RPM → 6s between calls
GEMINI_VALIDATOR_CONCURRENCY=10              # max concurrent calls; raise to 20+ on Tier 1
```

### Validation Path — Multi-LLM Panel (Groq)

```env
# Provider
LLM_PROVIDER=groq
LLM_API_KEY=gsk_your_groq_key_here
LLM_BASE_URL=https://api.groq.com/openai/v1

# Panel agent models (Groq paid subscription)
LLM_PANEL_TECH_MODEL=meta-llama/llama-4-scout-17b-16e-instruct
LLM_PANEL_SENT_MODEL=llama-3.1-8b-instant
LLM_PANEL_RISK_MODEL=meta-llama/llama-4-scout-17b-16e-instruct
LLM_PANEL_MODERATOR_MODEL=meta-llama/llama-4-maverick-17b-128e-instruct

# Panel behaviour
USE_MULTI_LLM_PANEL=true
LLM_PANEL_MAX_TOKENS=512
LLM_TEMPERATURE=0.2

# Consensus weights (must sum to 1.0)
PANEL_TECH_WEIGHT=0.50         # technical analysis weight
PANEL_SENT_WEIGHT=0.20         # sentiment weight (lower = better for sparse NSE news)
PANEL_RISK_WEIGHT=0.30         # risk management weight

# Rate-limit mitigation
PANEL_SEQUENTIAL_MODE=false    # true = run agents one-at-a-time
PANEL_AGENT_DELAY=1.0          # seconds between agents in sequential mode
```

### Post-Panel Validators (Panel path only)

```env
# Gemini Sentiment Validation (Step 4b, optional)
USE_GEMINI_SENTIMENT=true
GEMINI_SENTIMENT_API_KEY=your_key            # https://aistudio.google.com/apikey
GEMINI_SENTIMENT_MODEL=gemini-2.5-flash
GEMINI_SENTIMENT_RATE_DELAY=1.0

# Claude Live Validation (Step 4c, optional)
USE_LIVE_VALIDATION=true
LIVE_API_KEY=sk-ant-your_key_here            # https://console.anthropic.com/settings/keys
LIVE_MODEL=claude-opus-4-6

# MarketAux News/Sentiment (optional, enriches SENTIMENT agent)
USE_MARKETAUX=true
MARKETAUX_API_KEY=your_token_here            # https://www.marketaux.com/account/dashboard
MARKETAUX_MAX_ARTICLES=3
MARKETAUX_RATE_DELAY=0.5
```

### Free-Tier Fallback Models (Groq Panel)

```env
LLM_PANEL_TECH_MODEL=llama-3.3-70b-versatile
LLM_PANEL_SENT_MODEL=llama-3.1-8b-instant
LLM_PANEL_RISK_MODEL=meta-llama/llama-4-scout-17b-16e-instruct
LLM_PANEL_MODERATOR_MODEL=llama-3.3-70b-versatile
```

### Alternative LLM Providers (Single-LLM mode)

```env
# Ollama (local, no API key)
LLM_PROVIDER=ollama
LLM_MODEL=llama3.1:8b

# Gemini (free tier)
LLM_PROVIDER=gemini
LLM_MODEL=gemini-2.0-flash

# OpenAI
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
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

**Minimal setup (Gemini Direct Validator — recommended):**

```env
# Upstox (required) -- get token at https://upstox.com/developer/
UPSTOX_ACCESS_TOKEN=your_upstox_token_here

# Gemini Direct Validator (recommended -- 1 call per signal, live Google Search)
USE_GEMINI_VALIDATOR=true
GEMINI_VALIDATOR_API_KEY=your_gemini_key   # https://aistudio.google.com/apikey
```

**Full setup (Groq Panel + all validators):**

```env
# Upstox (required)
UPSTOX_ACCESS_TOKEN=your_upstox_token_here

# Groq (multi-LLM panel)
LLM_API_KEY=gsk_your_key_here
LLM_PROVIDER=groq
LLM_PANEL_TECH_MODEL=meta-llama/llama-4-scout-17b-16e-instruct
LLM_PANEL_SENT_MODEL=llama-3.1-8b-instant
LLM_PANEL_RISK_MODEL=meta-llama/llama-4-scout-17b-16e-instruct
LLM_PANEL_MODERATOR_MODEL=meta-llama/llama-4-maverick-17b-128e-instruct

# Post-panel validators (optional)
USE_GEMINI_SENTIMENT=true
GEMINI_SENTIMENT_API_KEY=your_gemini_key
USE_LIVE_VALIDATION=true
LIVE_API_KEY=sk-ant-your_key_here
```

### 5. Authenticate Upstox

```bash
python main.py auth
```

This opens the Upstox login page in your browser and automatically writes the new token to `.env`.

### 6. Run

```bash
python main.py scan
```

---

## Usage

```bash
# Run full scan (downloads data, detects signals, validates, enters positions)
python main.py scan

# Force re-download all OHLCV data (bypass cache)
python main.py scan --force-refresh

# Scan against a specific past date (auto-routes to backtest if past date)
python main.py scan --date 2026-02-27

# Refresh Upstox access token (opens browser, writes new token to .env)
python main.py auth

# View current open portfolio
python main.py portfolio

# View date-wise breakout history (last 30 days)
python main.py log

# View last 7 days only
python main.py log --days 7

# Delete all breakout_log entries for a specific date (with confirmation prompt)
python main.py clear-log --date 2026-02-16

# Run as a scheduled daemon (auto-runs at 08:20 IST Mon-Fri)
python main.py schedule

# Backtesting -- validate signals from a past date
python main.py backtest --date 2026-02-01
python main.py backtest --date 2026-02-01 --days 15
```

### Sample Scan Output

```
============================================================
   NSE BREAKOUT AGENT – DAILY SCAN
============================================================
   Scan date : 2026-03-07

[1/5] Checking exit conditions...
  No exits triggered.

[2/5] Fetching market news...
  12 new articles cached.

[3/5] Loading NSE EQ universe...
  Universe: 1623 NSE EQ instruments (224 blacklisted removed).
  Done. Downloaded: 43 | From cache: 1574 | Skipped (open pos): 6

[4/5] Gemini Direct Validator (5 signal(s))...
      Model  : gemini-2.5-flash
      Source : Gemini + Google Search grounding (live news)
  [Gemini 1/5] RELIANCE       -> CONFIRM conf=8/10
  [Gemini 2/5] HDFCBANK       -> WEAK    conf=5/10
  [Gemini 3/5] TATAMOTORS     -> CONFIRM conf=9/10
  ...
  5 signal(s) saved to breakout_log.

[5/5] Results: 5 breakout candidate(s) found.
  CONFIRM : 3  |  WEAK : 1  |  REJECT : 1

==============================================================
  ★  TODAY'S TOP PICKS  —  2026-03-07  ★
  (Stage2 | LLM CONFIRM | Score≥10 | Vol≥1.8x | RSI≤75)
==============================================================
  #1  TATAMOTORS   ₹987.50    Score:16  RSI:63  Vol:2.4x  LLM:CONFIRM(9/10) [VCP]
      Entry ₹987.50  →  Target ₹1035.80  →  SL ₹963.22  (Risk 2.5% | 2R reward)

  #2  RELIANCE     ₹1284.50   Score:14  RSI:67  Vol:2.1x  LLM:CONFIRM(8/10)
      Entry ₹1284.50  →  Target ₹1345.78  →  SL ₹1253.86  (Risk 2.4% | 2R reward)
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
| **Expectancy** | `(win_rate × avg_max_gain) + ((1 - win_rate) × avg_max_dd)` |

> **Note:** The backtest does not run LLM validation (would require API calls for historical dates).
> All outcomes are determined purely from cached local OHLCV data.

---

## Risk Management

The agent uses a layered exit strategy applied in priority order on every portfolio check:

```
1. STORED TARGET HIT   -> exit when price >= calculated 2R target (ATR-based)
2. PROFIT TARGET %     -> fallback ceiling at +10% (configurable)
3. TRAILING STOP       -> current_price - 1.5 × ATR14, ratcheted UP only (never down)
4. MAX HOLD DAYS       -> forced exit after 21 days regardless of PnL
```

**Stop loss calculation at entry:**
```
SL_atr   = buy_price - 1.5 × ATR14
SL_swing = swing_low × 0.99          (most recent local trough)
SL       = max(SL_atr, SL_swing)     <- tightest valid stop above zero
```

**Target calculation at entry:**
```
risk     = buy_price - SL
target   = buy_price + (risk × 2)    <- 2R reward-to-risk ratio
```

---

## Data Flow

```
Upstox API
    |  GET /v2/historical-candle/{instrument_key}/day/{to}/{from}
    v
upstox_client.py   --> instruments JSON (NSE.json.gz) -> symbol-key map
    |                  ETF filter (3-layer) -> invalid_instruments table
    v
database.py        --> ohlcv table  (cache; keyed by symbol+date)
    |
    v
technical.py       --> EMA20/50/200, RSI, MACD, Bollinger, ATR14,
                       Volume ratio, Supertrend, 20d high, 52w high/low
    |
    v
breakout_scanner.py -> score-based breakout signal  OR  pullback signal
                       (includes ema200, macd_hist, supertrend_dir in dict)
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
    ┌─────────────────────────────────────────────────────────────────┐
    │ Path A (USE_GEMINI_VALIDATOR=true)                              │
    │   gemini_validator.py  -> 1 Gemini call + Google Search        │
    │   -> verdict: CONFIRM / WEAK / REJECT                          │
    │   -> Steps 4b & 4c skipped                                     │
    ├─────────────────────────────────────────────────────────────────┤
    │ Path B (USE_MULTI_LLM_PANEL=true)                              │
    │   llm_panel.py -> 3 Groq agents + weighted consensus + debate  │
    │   -> verdict: CONFIRM / WEAK / REJECT                          │
    │   gemini_sentiment.py -> [4b, optional] Gemini + Google Search │
    │   live_validator.py   -> [4c, optional] Claude + web search    │
    └─────────────────────────────────────────────────────────────────┘
    |
    v
database.py        --> save_breakout_log()   (breakout_log table)
                   --> open_position()       (positions table)
                   --> save_signal()         (signals table)
    |
    v
html_report_writer.py --> reports/Scan-YYYY-MM-DD.html
```
