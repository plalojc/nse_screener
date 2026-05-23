from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .settings import AGENT_ROOT, scanner_python


STEP_PROGRESS = {
    "checking exit": 12,
    "fetching catalyst": 25,
    "loading nse": 32,
    "checking market news": 25,
    "loading ohlcv": 45,
    "llm gate": 66,
    "grok batch": 74,
    "gemini validation": 74,
    "results": 90,
    "html report saved": 98,
}


@dataclass
class ScanJob:
    id: str
    status: str = "queued"
    progress: int = 0
    message: str = "Queued"
    command: list[str] = field(default_factory=list)
    started_at: str | None = None
    ended_at: str | None = None
    exit_code: int | None = None
    lines: list[str] = field(default_factory=list)
    line_queue: "queue.Queue[str]" = field(default_factory=queue.Queue)

    def append(self, line: str) -> None:
        clean = line.rstrip("\r\n")
        if not clean:
            return
        self.lines.append(clean)
        if len(self.lines) > 2000:
            self.lines = self.lines[-2000:]
        self.line_queue.put(clean)
        self.message = clean[-220:]
        self.progress = max(self.progress, infer_progress(clean, self.progress))

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "exit_code": self.exit_code,
            "lines": self.lines[-300:],
            "command": self.command,
        }


def infer_progress(line: str, current: int) -> int:
    lowered = line.lower()
    for token, progress in STEP_PROGRESS.items():
        if token in lowered:
            return progress

    match = re.search(r"\[(\s*\d+)/(\d+)\]", line)
    if match:
        done = int(match.group(1))
        total = max(1, int(match.group(2)))
        scan_progress = 35 + int((done / total) * 25)
        return max(current, min(65, scan_progress))
    return current


class ScannerJobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, ScanJob] = {}
        self._lock = threading.Lock()

    def start_scan(self, scan_date: str | None = None, force_refresh: bool = False) -> ScanJob:
        with self._lock:
            for job in self._jobs.values():
                if job.status in {"queued", "running"}:
                    return job

            job_id = uuid.uuid4().hex[:12]
            command = [scanner_python(), "main.py", "scan"]
            if scan_date:
                command.extend(["--date", scan_date])
            if force_refresh:
                command.append("--force-refresh")
            job = ScanJob(id=job_id, command=command)
            self._jobs[job_id] = job

        thread = threading.Thread(target=self._run_job, args=(job,), daemon=True)
        thread.start()
        return job

    def _run_job(self, job: ScanJob) -> None:
        job.status = "running"
        job.progress = 3
        job.started_at = datetime.now().isoformat(timespec="seconds")
        job.append("Starting scanner...")

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            process = subprocess.Popen(
                job.command,
                cwd=str(AGENT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
            )
            assert process.stdout is not None
            for line in process.stdout:
                job.append(line)
            job.exit_code = process.wait()
            job.ended_at = datetime.now().isoformat(timespec="seconds")
            if job.exit_code == 0:
                job.status = "success"
                job.progress = 100
                job.append("Scanner completed successfully.")
            else:
                job.status = "failed"
                job.progress = max(job.progress, 95)
                job.append(f"Scanner failed with exit code {job.exit_code}.")
        except Exception as exc:
            job.status = "failed"
            job.ended_at = datetime.now().isoformat(timespec="seconds")
            job.exit_code = -1
            job.append(f"Scanner failed: {exc}")

    def get(self, job_id: str) -> ScanJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def latest(self) -> ScanJob | None:
        with self._lock:
            if not self._jobs:
                return None
            return list(self._jobs.values())[-1]

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            return [job.snapshot() for job in reversed(list(self._jobs.values()))]


def sse_event(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


def ensure_agent_root() -> Path:
    if not (AGENT_ROOT / "main.py").exists():
        raise RuntimeError(f"Scanner project root not found: {AGENT_ROOT}")
    return AGENT_ROOT
