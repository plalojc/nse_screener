# NSE Breakout Agent

A focused NSE equity breakout scanner.

The project now uses only:

- NSE Bhavcopy for NSE instruments/OHLCV data
- Gemini or Grok to validate trade signals
- SQLite for local cache/history
- HTML reports for scan and backtest output

## Project Structure

```text
nse_breakout_agent/
|-- main.py
|-- config.py
|-- scheduler.py
|-- requirements.txt
|-- agent/
|   |-- screener_agent.py
|   |-- portfolio_tracker.py
|-- analysis/
|   |-- technical.py
|   |-- breakout_scanner.py
|   |-- pattern_scanner.py
|   |-- catalyst_news.py
|   |-- theme_mapper.py
|   |-- gemini_validator.py
|   |-- grok_validator.py
|   |-- backtester.py
|-- data/
|   |-- nse_bhavcopy_client.py
|   |-- database.py
|-- report/
|   |-- html_report_writer.py
|   |-- backtest_report_writer.py
```

## Setup

```powershell
python -m venv venv
.\venv\Scripts\pip.exe install -r requirements.txt
copy env.example .env
```

Edit `.env` and set:

```env
LLM_VALIDATOR=gemini
GEMINI_VALIDATOR_API_KEY=...
LLM_VALIDATION_LIMIT=100
```

For Grok:

```env
LLM_VALIDATOR=grok
XAI_API_KEY=...
LLM_VALIDATION_LIMIT=100
```

`LLM_VALIDATION_LIMIT` controls how many top locally ranked stocks are sent to
Gemini or Grok. Set it to `0` to validate every signal.

Run a scan:

```powershell
.\venv\Scripts\python.exe main.py scan
```

The scanner now uses the product defaults directly: Stage2 breakouts, Stage1
pre-breakout setups, pullbacks, and news-driven fill candidates are ranked
locally, then only the best `LLM_VALIDATION_LIMIT` names are sent to the LLM.

## NSE Bhavcopy Data

Run:

```powershell
.\venv\Scripts\python.exe main.py scan
```

The scanner downloads missing weekday Bhavcopy files with `jugaad-data`, filters `SERIES == EQ`, stores OHLCV in `nse_bhavcopy.db`, and runs the breakout logic over that cache.

## Report Filters

HTML reports show confirmed/recommended stocks by default:

```env
REPORT_INCLUDE_WEAK=false
```

Set `REPORT_INCLUDE_WEAK=true` if you want borderline LLM verdicts in the report.

## Catalyst News

The scanner automatically caches catalyst events before LLM validation. It looks
for NSE corporate announcements such as results, order wins, block/bulk
deals, approvals, expansion, and capital actions. It also scans PIB policy RSS
for sector motivation, maps policy themes through `analysis/theme_mapper.py`,
and optionally enriches those maps from NSE index constituent CSVs when they are
available. Source failures are isolated: if NSE, PIB, or an index CSV is down,
the scan continues with cached/local data. Catalyst events are saved in
`catalyst_events`; direct company catalysts and policy-theme candidates can fill
the LLM queue as `NEWS` candidates after Stage2 breakouts and Stage1 setups.

## Commands

```powershell
.\venv\Scripts\python.exe main.py scan
.\venv\Scripts\python.exe main.py scan --force-refresh
.\venv\Scripts\python.exe main.py portfolio
.\venv\Scripts\python.exe main.py log --days 30
.\venv\Scripts\python.exe main.py backtest --date 2026-02-16 --days 30
.\venv\Scripts\python.exe main.py schedule
```

## UI Portal

The `screener_ui` folder contains a FastAPI + React portal for running scans,
scheduling daily scans, viewing/downloading HTML reports, managing a watchlist,
and tracking bought shares with current P/L from cached Bhavcopy prices.

```powershell
.\venv\Scripts\pip.exe install -r screener_ui\backend\requirements.txt
cd screener_ui
.\start_backend.ps1
```

Open `http://127.0.0.1:8787` after building the frontend. For local frontend
development, run `.\start_frontend.ps1` from `screener_ui`. Use
`.\stop_backend.ps1`, `.\stop_frontend.ps1`, or `.\stop_all.ps1` to stop the UI
services. Matching `.cmd` scripts are also available, for example
`start_all.cmd` and `stop_all.cmd`.

## Flow

1. Load NSE EQ instruments from NSE Bhavcopy.
2. Filter invalid instruments and ETFs.
3. Bulk-load OHLCV from the SQLite Bhavcopy cache.
4. Cheaply prefilter raw candles before calculating heavier technical indicators.
5. Detect the built-in setup mix.
   - Breakouts must clear a prior 20/55-day high.
   - Local filters prefer Stage2 trend, healthy volume, liquidity, strong close, and manageable stop distance.
   - Stage1 watchlist names must be liquid, close strongly, sit near a 20/55-day trigger, and show constructive RSI/compression.
   - Optional Watchlist fill names are lower-priority candidates used only to fill the LLM review queue.
   - News-driven names come from cached catalyst events such as results, deals, order wins, approvals, or government policy themes.
   - Technical signals with a direct or mapped catalyst are boosted within their own priority bucket before LLM selection.
6. Rank signals locally and validate only the top `LLM_VALIDATION_LIMIT` stocks with the configured LLM validator.
   - Gemini validates per signal with Google Search grounding.
   - Grok validates compact batches through xAI's OpenAI-compatible API.
7. Save signal history to SQLite.
8. Print candidates, top picks, portfolio entries, and an HTML report.

## Notes

- Gemini and Grok are the supported decision engines.
- The project intentionally keeps two SQLite files: `nse_agent.db` for app state and `nse_bhavcopy.db` for the larger market-data cache.
- Generated reports and the SQLite DB are local runtime artifacts and are ignored by Git.
