# NSE Screener UI

FastAPI + React portal for the NSE breakout scanner.

The UI uses the same database mode as the scanner. With no `DATABASE_URL`, it
stores UI state in local SQLite. With `DATABASE_URL`, watchlist, holdings, and
UI settings are stored in the configured user schema.

Report pages are rendered from scanner database rows. Static HTML report files
are not required; downloads generate the HTML content on demand.

Use the Settings page to change the TradingView chart id, LLM validation limit,
and whether WEAK verdicts are included in rendered reports.

## Structure

```text
screener_ui/
|-- backend/
|   |-- app.py
|   |-- reports.py
|   |-- runtime.py
|   |-- scanner_runner.py
|   |-- settings.py
|   |-- store.py
|   |-- requirements.txt
|   |-- routes/
|-- frontend/
|   |-- package.json
|   |-- src/
|       |-- App.jsx
|       |-- api.js
|       |-- components/
|       |-- hooks/
|       |-- pages/
|       |-- utils/
```

## Backend

Backend scripts live in the project root:

```powershell
cd C:\sharemarketWork\ShareMarketDemo\nse_breakout_agent
.\run_backend.ps1
.\stop_backend.ps1
```

By default the backend uses the parent folder as the scanner root. If this UI
folder is moved elsewhere, set `SCREENER_AGENT_ROOT` before starting the backend:

```powershell
$env:SCREENER_AGENT_ROOT="C:\sharemarketWork\ShareMarketDemo\nse_breakout_agent"
```

If you want to use a specific Python interpreter, set:

```powershell
$env:SCREENER_AGENT_PYTHON="C:\sharemarketWork\ShareMarketDemo\nse_breakout_agent\venv\Scripts\python.exe"
```

## Frontend

From `screener_ui\frontend`:

```powershell
npm install
```

From `screener_ui`:

```powershell
.\run_ui.ps1
.\stop_ui.ps1
```

Open `http://127.0.0.1:5173` for Vite dev mode.

For production:

```powershell
cd frontend
npm run build
```

The FastAPI app serves `frontend/dist` automatically when the build exists.
In production mode you only need the root `.\run_backend.ps1` and then open
`http://127.0.0.1:8787`.
