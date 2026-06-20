# Zoho Catalyst Deployment

Use **Catalyst AppSail** for this project. FastAPI is a normal ASGI web app, and
AppSail is designed for standalone web services with a startup command and
runtime port. Catalyst Advanced I/O Functions use a Catalyst-specific
`handler(request)` function style, so they are not the best fit for this
FastAPI app without a rewrite.

## Build The Deploy Folder

From the project root:

```powershell
.\venv\Scripts\python.exe tools\build_catalyst_appsail.py
```

This creates:

```text
catalyst_deploy/
`-- my-unified-app/
    |-- catalyst.json
    |-- backend/
    |   |-- main.py          # AppSail/FastAPI entry point
    |   |-- scanner_main.py  # Scanner CLI entry point used by scan jobs
    |   |-- app-config.json
    |   |-- requirements.txt
    |   |-- agent/
    |   |-- analysis/
    |   |-- data/
    |   |-- report/
    |   `-- screener_ui/backend/
    `-- frontend/
        |-- package.json
        |-- src/
        `-- dist/
```

The React `dist` is also copied into:

```text
backend/screener_ui/frontend/dist
```

That lets FastAPI serve both the UI and API from one AppSail service.

## Create A Separate Sibling App Folder

To avoid disturbing this working project, generate the deploy copy here:

```powershell
.\venv\Scripts\python.exe tools\build_catalyst_appsail.py --output C:\sharemarketWork\ShareMarketDemo\nse_screener
```

That creates:

```text
C:\sharemarketWork\ShareMarketDemo\nse_screener
|-- catalyst.json
|-- backend/
`-- frontend/
```

## Do Not Use Import Project

Do not use `Import-project` for `nse_screener.zip`. Catalyst import requires an
exported IaC template file named like `project-template-1.0.0.json` at the root
of the zip. Zoho's docs say that template is normally generated through
`catalyst iac:export` / `catalyst iac:pack` from an existing Catalyst project.

For this app, use AppSail deploy instead.

## Deploy Target

Deploy from this folder:

```text
C:\sharemarketWork\ShareMarketDemo\nse_screener
```

If you see `Project info is not present`, the folder is not linked to a
Catalyst project yet. Run this once:

```powershell
cd C:\sharemarketWork\ShareMarketDemo\nse_screener
catalyst init
```

Then choose one of these:

- Create a new Catalyst project named `nse-screener`, or select an existing
  project.
- Do not import a zip.
- Do not add Functions or Web Client components here; AppSail is already
  configured by this folder.

After `catalyst init`, the CLI should create `.catalystrc` in this folder. If
the CLI rewrites `catalyst.json`, regenerate the deploy folder from the original
project. The builder preserves `.catalystrc`:

```powershell
cd C:\sharemarketWork\ShareMarketDemo\nse_breakout_agent
.\venv\Scripts\python.exe tools\build_catalyst_appsail.py --output C:\sharemarketWork\ShareMarketDemo\nse_screener --skip-npm-build
```

The root `catalyst.json` points AppSail to:

```text
C:\sharemarketWork\ShareMarketDemo\nse_screener\backend
```

Run:

```powershell
catalyst deploy appsail
```

If Catalyst prompts for a build path, choose:

```text
C:\sharemarketWork\ShareMarketDemo\nse_screener\backend
```

Startup command:

```sh
sh -c 'if [ ! -d lib/uvicorn ]; then python3 -m pip install --disable-pip-version-check --no-cache-dir -r requirements.txt -t lib || exit 1; fi; python3 main.py'
```

`main.py` reads Catalyst's `X_ZOHO_CATALYST_LISTEN_PORT` environment variable
and starts Uvicorn on that port. The scan runner calls `scanner_main.py`, which
keeps the original scanner CLI separate from the AppSail web entry point.

## Restart Or Redeploy After Environment Changes

After changing AppSail environment variables in the Catalyst Console, restart
the AppSail service from the console if the restart option is available.

The simple CLI fallback is to redeploy:

```powershell
cd C:\sharemarketWork\ShareMarketDemo\nse_screener
catalyst deploy appsail
```

If Catalyst asks for the details again, use:

```text
AppSail name: nse-appsail
Build directory: C:\sharemarketWork\ShareMarketDemo\nse_screener\backend
Stack: Python 3.13
Command: sh -c 'if [ ! -d lib/uvicorn ]; then python3 -m pip install --disable-pip-version-check --no-cache-dir -r requirements.txt -t lib || exit 1; fi; python3 main.py'
```

If you already deployed from `C:\sharemarketWork\ShareMarketDemo\nse_screener`
instead, redeploy once with the backend build directory above. If you still want
to deploy from the root folder, use this command:

```text
sh -c 'if [ ! -d backend/lib/uvicorn ]; then python3 -m pip install --disable-pip-version-check --no-cache-dir -r backend/requirements.txt -t backend/lib || exit 1; fi; python3 backend/main.py'
```

The generated deploy folder includes `requirements.txt` in both the root folder
and the backend folder so dependencies are installed for either build directory,
but the backend folder is the cleaner AppSail build path. The first AppSail
startup can take longer while dependencies are installed into `lib`; later
starts should reuse that folder.

For Catalyst, the generated `requirements.txt` uses plain `uvicorn` instead of
`uvicorn[standard]` to avoid downloading optional compiled extras such as
`uvloop` and `watchfiles` during AppSail startup.

## Required Environment Variables

Set these in the Catalyst AppSail console:

```env
DATABASE_URL=postgresql://...
SCREENER_JWT_SECRET=use-a-long-random-secret
XAI_API_KEY=...
```

Optional:

```env
PG_DUMP_PATH=/usr/bin/pg_dump
```

## Important Notes

- Do not upload local `.env`, SQLite `.db` files, `users.json`, or `node_modules`.
- `users.example.json` is included, but the real admin/user file must be created
  through the app or supplied securely on the server.
- Supabase Postgres remains the right database backend for Catalyst deployment.
