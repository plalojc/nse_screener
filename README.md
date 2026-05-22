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
|   |-- news_fetcher.py
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
NSE_BHAVCOPY_DB_PATH=nse_bhavcopy.db
NSE_BHAVCOPY_DIR=data/bhavcopy
GEMINI_VALIDATOR_API_KEY=...
```

Choose the validator:

```env
LLM_VALIDATOR=gemini
```

or:

```env
LLM_VALIDATOR=grok
XAI_API_KEY=...
GROK_VALIDATOR_MODEL=grok-4.20-reasoning
GROK_VALIDATOR_BATCH_SIZE=10
LLM_VALIDATION_LIMIT=100
```

`LLM_VALIDATION_LIMIT` controls how many top locally ranked stocks are sent to
Gemini or Grok. Set it to `0` to validate every signal.

Run a scan:

```powershell
.\venv\Scripts\python.exe main.py scan
```

## NSE Bhavcopy Data

Run:

```powershell
.\venv\Scripts\python.exe main.py scan
```

The scanner downloads missing weekday Bhavcopy files with `jugaad-data`, filters `SERIES == EQ`, stores OHLCV in `nse_bhavcopy.db`, and runs the breakout logic over that cache.

## Commands

```powershell
.\venv\Scripts\python.exe main.py scan
.\venv\Scripts\python.exe main.py scan --force-refresh
.\venv\Scripts\python.exe main.py portfolio
.\venv\Scripts\python.exe main.py log --days 30
.\venv\Scripts\python.exe main.py backtest --date 2026-02-16 --days 30
.\venv\Scripts\python.exe main.py schedule
```

## Flow

1. Load NSE EQ instruments from NSE Bhavcopy.
2. Filter invalid instruments and ETFs.
3. Load OHLCV from SQLite cache or fetch fresh data.
4. Detect breakout and pullback setups.
5. Rank signals locally and validate only the top `LLM_VALIDATION_LIMIT` stocks with the configured LLM validator.
   - Gemini validates per signal with Google Search grounding.
   - Grok validates compact batches through xAI's OpenAI-compatible API.
6. Save signal history to SQLite.
7. Print candidates, top picks, portfolio entries, and an HTML report.

## Notes

- Gemini and Grok are the supported decision engines.
- Generated reports and the SQLite DB are local runtime artifacts and are ignored by Git.
