# NSE Breakout Agent

A focused NSE equity breakout scanner.

The project now uses only:

- NSE Bhavcopy for NSE instruments/OHLCV data
- Gemini or Grok to validate trade signals
- SQLite by default, with optional Postgres for larger multi-year history
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

The scanner downloads missing weekday Bhavcopy files with `jugaad-data`, filters `SERIES == EQ`, stores OHLCV in the local cache, and runs the breakout logic over that cache.

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
scheduling daily scans, viewing reports from database rows, downloading HTML
reports on demand, managing a watchlist, and tracking holdings P/L from cached
Bhavcopy prices. The Settings page controls the TradingView chart id, LLM
validation limit, and whether WEAK verdicts appear in reports.

```powershell
.\venv\Scripts\pip.exe install -r requirements.txt
.\run_screener.bat start
```

Open `http://127.0.0.1:8787`. The combined launcher builds the React frontend
and starts FastAPI as the single backend + UI process.

Combined launcher commands:

```powershell
.\run_screener.bat start
.\run_screener.bat stop
.\run_screener.bat restart
.\run_screener.bat status
```

## Flow

1. Load NSE EQ instruments from NSE Bhavcopy.
2. Filter invalid instruments and ETFs.
3. Bulk-load OHLCV from the Bhavcopy cache.
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
7. Save signal history to the configured database.
8. Print candidates, top picks, portfolio entries, and an HTML report.

## Notes

- Gemini and Grok are the supported decision engines.
- SQLite is the zero-config default. For heavier history, set `DATABASE_URL` to use Postgres.
- In Postgres mode, common scanner/market tables are created in the `system` schema, and user-owned tables are created in the `app_user` schema by default.
- Local SQLite DB files are runtime artifacts and are ignored by Git. HTML
  reports are rendered from database rows when viewed or downloaded.

## Postgres Mode

SQLite is fine for quick local runs, but Postgres is the better path once the
Bhavcopy cache grows past a year or when the UI will support multiple users.

Set this in `.env`:

```env
DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/nse_breakout
DB_SYSTEM_SCHEMA=system
DB_USER_SCHEMA=app_user
```

Then install the driver and initialize tables with any normal command:

```powershell
.\venv\Scripts\pip.exe install -r requirements.txt
.\venv\Scripts\python.exe main.py log
```

To copy current local SQLite data into Postgres after `DATABASE_URL` is set:

```powershell
.\venv\Scripts\python.exe tools\migrate_sqlite_to_postgres.py
```

Use `--replace` only when you want the target Postgres tables cleared before
copying from the local SQLite files.
