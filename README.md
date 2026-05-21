# NSE Breakout Agent

A focused NSE equity breakout scanner.

The project now uses only:

- Upstox for NSE instruments, OHLCV data, and live prices
- Gemini with Google Search grounding to validate trade signals
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
|   |-- backtester.py
|-- auth/
|   |-- upstox_auth.py
|-- data/
|   |-- upstox_client.py
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
UPSTOX_CLIENT_ID=...
UPSTOX_CLIENT_SECRET=...
UPSTOX_REDIRECT_URI=http://127.0.0.1:8765/callback
GEMINI_VALIDATOR_API_KEY=...
```

Refresh the Upstox token:

```powershell
.\venv\Scripts\python.exe main.py auth
```

Run a scan:

```powershell
.\venv\Scripts\python.exe main.py scan
```

## Commands

```powershell
.\venv\Scripts\python.exe main.py scan
.\venv\Scripts\python.exe main.py scan --force-refresh
.\venv\Scripts\python.exe main.py portfolio
.\venv\Scripts\python.exe main.py log --days 30
.\venv\Scripts\python.exe main.py backtest --date 2026-02-16 --days 30
.\venv\Scripts\python.exe main.py schedule
.\venv\Scripts\python.exe main.py auth
```

## Flow

1. Load NSE EQ instruments from Upstox.
2. Filter invalid instruments and ETFs.
3. Load OHLCV from SQLite cache or fetch fresh data from Upstox.
4. Detect breakout and pullback setups.
5. Validate each signal with Gemini and Google Search grounding.
6. Save signal history to SQLite.
7. Print candidates, top picks, portfolio entries, and an HTML report.

## Notes

- Upstox access tokens must still be approved through the official Upstox login flow.
- Gemini is the only decision engine in this codebase.
- Generated reports and the SQLite DB are local runtime artifacts and are ignored by Git.
