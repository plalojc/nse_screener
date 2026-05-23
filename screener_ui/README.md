# NSE Screener UI

FastAPI + React portal for the NSE breakout scanner.

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

From `screener_ui`:

```powershell
..\venv\Scripts\pip.exe install -r backend\requirements.txt
.\start_backend.ps1
.\stop_backend.ps1
```

The same commands are also available as `.cmd` files, for example
`start_backend.cmd` and `stop_backend.cmd`.

By default the backend uses the parent folder as the scanner root. If this UI
folder is moved elsewhere, set:

```powershell
$env:SCREENER_AGENT_ROOT="C:\sharemarketWork\ShareMarketDemo\nse_breakout_agent"
```

## Frontend

From `screener_ui\frontend`:

```powershell
npm install
```

From `screener_ui`:

```powershell
.\start_frontend.ps1
.\stop_frontend.ps1
```

Open `http://127.0.0.1:5173` for Vite dev mode.

To start or stop both services together:

```powershell
.\start_all.ps1
.\stop_all.ps1
```

If PowerShell script execution is disabled on your machine, use
`start_all.cmd` and `stop_all.cmd` instead.

For production:

```powershell
cd frontend
npm run build
```

The FastAPI app serves `frontend/dist` automatically when the build exists.
In production mode you only need `.\start_backend.ps1` and then open
`http://127.0.0.1:8787`.
