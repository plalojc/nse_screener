from __future__ import annotations

import os
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent
UI_ROOT = BACKEND_DIR.parent
DEFAULT_AGENT_ROOT = UI_ROOT.parent

AGENT_ROOT = Path(os.getenv("SCREENER_AGENT_ROOT", str(DEFAULT_AGENT_ROOT))).resolve()
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

BHAVCOPY_DB_PATH = AGENT_ROOT / "nse_bhavcopy.db"
UI_DB_PATH = Path(os.getenv("SCREENER_UI_DB", str(BACKEND_DIR / "ui_state.db"))).resolve()


def scanner_python() -> str:
    configured = os.getenv("SCREENER_AGENT_PYTHON")
    if configured:
        return configured

    windows_venv = AGENT_ROOT / "venv" / "Scripts" / "python.exe"
    posix_venv = AGENT_ROOT / "venv" / "bin" / "python"
    if windows_venv.exists():
        return str(windows_venv)
    if posix_venv.exists():
        return str(posix_venv)
    return sys.executable
