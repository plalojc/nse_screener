from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from data.database import init_db
from .routes import auth, backup, bootstrap, dashboard, portfolio, reports, scan, scheduler as scheduler_routes, settings as settings_routes
from .auth import ensure_admin_user
from .runtime import apply_schedule, scheduler
from .scanner_runner import ensure_agent_root
from .settings import UI_ROOT
from .store import get_setting, init_store


app = FastAPI(title="NSE Breakout Screener UI", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(bootstrap.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(scan.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(portfolio.router, prefix="/api")
app.include_router(scheduler_routes.router, prefix="/api")
app.include_router(settings_routes.router, prefix="/api")
app.include_router(backup.router, prefix="/api")


class ReactStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise
        if response.status_code == 404:
            return await super().get_response("index.html", scope)
        return response


@app.on_event("startup")
def startup() -> None:
    ensure_agent_root()
    init_db()
    ensure_admin_user()
    init_store()
    scheduler.start()
    enabled = get_setting("scheduler_enabled", "false") == "true"
    scan_time = get_setting("scheduler_time", "08:20")
    if enabled:
        apply_schedule(scan_time)


@app.on_event("shutdown")
def shutdown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)


dist_dir = UI_ROOT / "frontend" / "dist"
if dist_dir.exists():
    app.mount("/", ReactStaticFiles(directory=dist_dir, html=True), name="frontend")
