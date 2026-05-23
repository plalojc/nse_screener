from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


UI_ROOT = Path(__file__).resolve().parents[1]
AGENT_ROOT = UI_ROOT.parent
FRONTEND_DIR = UI_ROOT / "frontend"
RUNTIME_DIR = UI_ROOT / ".runtime"
LOG_DIR = UI_ROOT / "logs"


def ensure_dirs() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def port_pid(port: int) -> int | None:
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None

    marker = f":{port}"
    for line in result.stdout.splitlines():
        if marker not in line or "LISTENING" not in line.upper():
            continue
        parts = line.split()
        if len(parts) >= 5 and parts[-1].isdigit():
            return int(parts[-1])
    return None


def write_pid(name: str, process_id: int) -> None:
    (RUNTIME_DIR / f"{name}.pid").write_text(str(process_id), encoding="utf-8")


def read_pid(name: str) -> int | None:
    pid_file = RUNTIME_DIR / f"{name}.pid"
    if not pid_file.exists():
        return None
    try:
        return int(pid_file.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def remove_pid(name: str) -> None:
    (RUNTIME_DIR / f"{name}.pid").unlink(missing_ok=True)


def start_process(name: str, command: list[str], cwd: Path, port: int) -> None:
    ensure_dirs()
    existing = port_pid(port)
    if existing:
        write_pid(name, existing)
        print(f"{name.title()} already running at http://127.0.0.1:{port} (PID {existing}).")
        return

    stdout = open(LOG_DIR / f"{name}.out.log", "a", encoding="utf-8")
    stderr = open(LOG_DIR / f"{name}.err.log", "a", encoding="utf-8")
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdout=stdout,
        stderr=stderr,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    write_pid(name, process.pid)
    time.sleep(3)

    listening = port_pid(port)
    if listening:
        write_pid(name, listening)
        print(f"{name.title()} started at http://127.0.0.1:{port} (PID {listening}).")
    else:
        print(f"{name.title()} process started (PID {process.pid}), but port {port} is not listening yet.")
        print(f"Check logs: {LOG_DIR / f'{name}.err.log'}")


def stop_pid(process_id: int) -> bool:
    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/PID", str(process_id), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0

    try:
        os.kill(process_id, 15)
        return True
    except OSError:
        return False


def stop_service(name: str, port: int) -> None:
    stopped = False
    process_id = read_pid(name)
    if process_id:
        stopped = stop_pid(process_id)
        remove_pid(name)
        if stopped:
            print(f"{name.title()} stopped (PID {process_id}).")

    listening = port_pid(port)
    if listening:
        stopped = stop_pid(listening) or stopped
        if stopped:
            print(f"{name.title()} stopped from port {port} (PID {listening}).")

    if not stopped:
        print(f"{name.title()} is not running.")


def start_backend() -> None:
    python = sys.executable
    command = [python, "-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1", "--port", "8787"]
    start_process("backend", command, UI_ROOT, 8787)


def start_frontend() -> None:
    npm = shutil.which("npm.cmd") or shutil.which("npm") or "npm.cmd"
    node_modules = FRONTEND_DIR / "node_modules"
    if not node_modules.exists():
        print("Installing frontend packages...")
        subprocess.run([npm, "install"], cwd=str(FRONTEND_DIR), check=True)
    command = [npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173"]
    start_process("frontend", command, FRONTEND_DIR, 5173)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=("start-backend", "stop-backend", "start-frontend", "stop-frontend"),
    )
    args = parser.parse_args()

    if args.command == "start-backend":
        start_backend()
    elif args.command == "stop-backend":
        stop_service("backend", 8787)
    elif args.command == "start-frontend":
        start_frontend()
    elif args.command == "stop-frontend":
        stop_service("frontend", 5173)


if __name__ == "__main__":
    main()
