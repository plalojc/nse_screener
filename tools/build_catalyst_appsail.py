from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "catalyst_deploy" / "my-unified-app"

BACKEND_DIRS = [
    "agent",
    "analysis",
    "data",
    "report",
    "screener_ui/backend",
]

BACKEND_FILES = [
    "config.py",
    "scheduler.py",
    "__init__.py",
]

FRONTEND_FILES = [
    "index.html",
    "package.json",
    "package-lock.json",
    "vite.config.js",
]


def appsail_requirements() -> str:
    lines = []
    for raw in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line == "uvicorn[standard]":
            line = "uvicorn"
        lines.append(line)
    return "\n".join(lines) + "\n"


def clean_dir(path: Path) -> None:
    preserved: dict[str, str] = {}
    for name in (".catalystrc",):
        preserved_path = path / name
        if preserved_path.exists() and preserved_path.is_file():
            preserved[name] = preserved_path.read_text(encoding="utf-8")
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    for name, content in preserved.items():
        (path / name).write_text(content, encoding="utf-8")


def copy_path(src: Path, dst: Path) -> None:
    if src.is_dir():
        shutil.copytree(
            src,
            dst,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.db", "users.json"),
        )
    elif src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def run(cmd: list[str], cwd: Path) -> None:
    if os.name == "nt" and cmd and cmd[0] == "npm":
        cmd = ["npm.cmd", *cmd[1:]]
    print(f"[run] {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, check=True)


def build_frontend(skip_npm_build: bool) -> None:
    frontend = ROOT / "screener_ui" / "frontend"
    if not skip_npm_build:
        run(["npm", "install"], frontend)
        run(["npm", "run", "build"], frontend)
    dist = frontend / "dist"
    if not dist.exists():
        raise SystemExit("Frontend dist folder not found. Run without --skip-npm-build first.")


def write_backend_files(backend: Path) -> None:
    (backend / "main.py").write_text(
        """from __future__ import annotations

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR / "lib"))
sys.path.insert(0, str(BASE_DIR))

import uvicorn

from screener_ui.backend.app import app


if __name__ == "__main__":
    port = int(os.getenv("X_ZOHO_CATALYST_LISTEN_PORT", os.getenv("PORT", "9000")))
    uvicorn.run(app, host="0.0.0.0", port=port)
""",
        encoding="utf-8",
    )
    (backend / "requirements.txt").write_text(
        appsail_requirements(),
        encoding="utf-8",
    )
    startup_command = (
        "sh -c 'python3 -c \"import uvicorn\" || "
        "python3 -m pip install --disable-pip-version-check --no-cache-dir -r requirements.txt -t lib || exit 1; "
        "python3 main.py'"
    )
    (backend / "app-config.json").write_text(
        """{
  "command": "%s",
  "stack": "python313",
  "memory": 1024,
    "env_variables": {
      "SCREENER_AGENT_ROOT": ".",
      "SCREENER_JWT_SECRET": "CHANGE_THIS_IN_CATALYST_CONSOLE",
      "DATABASE_URL": "SET_THIS_IN_CATALYST_CONSOLE",
      "XAI_API_KEY": "SET_THIS_IN_CATALYST_CONSOLE"
    }
  }
""" % startup_command,
        encoding="utf-8",
    )


def write_root_files(output: Path) -> None:
    (output / "catalyst.json").write_text(
        """{
  "appsail": [
    {
      "source": "backend",
      "name": "nse-screener"
    }
  ]
}
""",
        encoding="utf-8",
    )
    (output / "main.py").write_text(
        """from __future__ import annotations

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR / "lib"))
sys.path.insert(0, str(BASE_DIR / "backend"))

import uvicorn

from screener_ui.backend.app import app


if __name__ == "__main__":
    port = int(os.getenv("X_ZOHO_CATALYST_LISTEN_PORT", os.getenv("PORT", "9000")))
    uvicorn.run(app, host="0.0.0.0", port=port)
""",
        encoding="utf-8",
    )
    (output / "requirements.txt").write_text(
        appsail_requirements(),
        encoding="utf-8",
    )


def patch_deploy_scanner_runner(backend: Path) -> None:
    runner = backend / "screener_ui" / "backend" / "scanner_runner.py"
    text = runner.read_text(encoding="utf-8")
    text = text.replace(
        'command = [scanner_python(), "main.py", "scan"]',
        'command = [scanner_python(), "scanner_main.py", "scan"]',
    )
    text = text.replace(
        'if not (AGENT_ROOT / "main.py").exists():',
        'if not (AGENT_ROOT / "scanner_main.py").exists():',
    )
    text = text.replace(
        'env["PYTHONIOENCODING"] = "utf-8"',
        'env["PYTHONIOENCODING"] = "utf-8"\n'
        '        lib_path = str(AGENT_ROOT / "lib")\n'
        '        existing_pythonpath = env.get("PYTHONPATH", "")\n'
        '        env["PYTHONPATH"] = lib_path if not existing_pythonpath else lib_path + os.pathsep + existing_pythonpath',
    )
    runner.write_text(text, encoding="utf-8")


def build_package(output: Path, skip_npm_build: bool) -> None:
    build_frontend(skip_npm_build)

    backend = output / "backend"
    frontend = output / "frontend"
    clean_dir(output)
    backend.mkdir(parents=True, exist_ok=True)
    frontend.mkdir(parents=True, exist_ok=True)

    for rel in BACKEND_DIRS:
        copy_path(ROOT / rel, backend / rel)
    for rel in BACKEND_FILES:
        copy_path(ROOT / rel, backend / rel)
    copy_path(ROOT / "main.py", backend / "scanner_main.py")

    for rel in FRONTEND_FILES:
        copy_path(ROOT / "screener_ui" / "frontend" / rel, frontend / rel)
    copy_path(ROOT / "screener_ui" / "frontend" / "src", frontend / "src")
    copy_path(ROOT / "screener_ui" / "frontend" / "dist", frontend / "dist")

    copy_path(ROOT / "screener_ui" / "frontend" / "dist", backend / "screener_ui" / "frontend" / "dist")
    patch_deploy_scanner_runner(backend)
    write_backend_files(backend)
    write_root_files(output)

    (output / "README.md").write_text(
        """# NSE Screener Catalyst AppSail Package

This folder is generated by `python tools/build_catalyst_appsail.py`.

## Structure

```text
my-unified-app/
|-- catalyst.json
|-- backend/   # AppSail Python/FastAPI deployable app
|   |-- main.py          # AppSail/FastAPI entry point
|   |-- scanner_main.py  # Scanner CLI entry point used by scan jobs
|-- frontend/  # React source and production dist for reference
```

Deploy the AppSail service from this folder. The FastAPI backend serves the
React `dist` folder, so one AppSail service hosts both UI and API.

## AppSail Startup Command

```sh
sh -c 'python3 main.py'
```

The app reads Catalyst's `X_ZOHO_CATALYST_LISTEN_PORT` automatically.

## Deploy

Do not use `Import-project` for this zip. That command expects an exported
Catalyst IaC template with `project-template-*.json` at the zip root.

Use:

```sh
catalyst deploy appsail
```

or use Catalyst's standalone AppSail deploy and select `backend` as the build
path.

## Required Catalyst Environment Variables

Configure these in Catalyst AppSail, not in source control:

- `DATABASE_URL`
- `SCREENER_JWT_SECRET`
- `XAI_API_KEY`
- optional: `PG_DUMP_PATH` if admin Postgres backups need pg_dump
""",
        encoding="utf-8",
    )
    print(f"[done] Catalyst package created at: {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Zoho Catalyst AppSail deploy package.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--skip-npm-build", action="store_true")
    args = parser.parse_args()
    build_package(args.output.resolve(), args.skip_npm_build)


if __name__ == "__main__":
    main()
