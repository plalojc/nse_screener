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
from .user_settings import app_settings


STEP_PROGRESS = {
    "phase bhavcopy-cache started": 8,
    "phase bhavcopy-cache completed": 10,
    "phase exit-check started": 12,
    "phase universe-load started": 25,
    "phase universe-load completed": 32,
    "phase catalyst-fetch started": 34,
    "phase ohlcv-bulk-load started": 38,
    "phase ohlcv-bulk-load completed": 45,
    "phase technical-scan started": 48,
    "phase technical-scan completed": 64,
    "phase llm-validation started": 74,
    "phase llm-validation completed": 88,
    "phase save-breakout-log started": 90,
    "phase results started": 94,
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

NOISY_MESSAGE_PATTERNS = (
    re.compile(r"^\[\s*\d+/\d+\]"),
    re.compile(r"^\s*\[Grok\]\s+Evaluating batch", re.IGNORECASE),
    re.compile(r"^\s*\[Gemini\s+\d+/\d+\]", re.IGNORECASE),
)


def _should_log_scan_line(line: str) -> bool:
    clean = line.strip()
    if not clean:
        return False
    lowered = clean.lower()
    if any(pattern.search(clean) for pattern in NOISY_MESSAGE_PATTERNS):
        return False
    return any(token in lowered for token in (
        "starting scanner",
        "daily scan",
        "backtest",
        "scan date",
        "evaluating until",
        "[flow]",
        "[prices]",
        "bhavcopy",
        "checking exit",
        "fetching catalyst",
        "loading nse",
        "done. loaded from cache",
        "llm gate",
        "grok batch validation",
        "grok:",
        "results:",
        "html report saved",
        "scanner completed",
        "scanner failed",
        "traceback",
        "error",
        "exception",
        "modulenotfound",
    ))


def _log_scan_line(job_id: str, line: str) -> None:
    if _should_log_scan_line(line):
        print(f"[scan:{job_id}] {line.strip()}", flush=True)


def _last_useful_error(lines: list[str]) -> str:
    for line in reversed(lines):
        clean = line.strip()
        if not clean:
            continue
        lowered = clean.lower()
        if any(token in lowered for token in ("traceback", "error", "exception", "modulenotfound", "permission denied", "failed")):
            return clean[-240:]
    for line in reversed(lines):
        clean = line.strip()
        if clean and not any(pattern.search(clean) for pattern in NOISY_MESSAGE_PATTERNS):
            return clean[-240:]
    return ""


def public_message(line: str, fallback: str) -> str:
    clean = line.strip()
    if not clean:
        return fallback
    if any(pattern.search(clean) for pattern in NOISY_MESSAGE_PATTERNS):
        return fallback
    lowered = clean.lower()

    if "starting scanner" in lowered:
        return "Starting the scan..."
    if "scan date" in lowered:
        return "Preparing market data for the selected date..."
    if "bhavcopy" in lowered:
        return "Loading NSE daily market data..."
    if "checking exit" in lowered or "[prices]" in lowered:
        return "Checking latest prices and open positions..."
    if "loading nse" in lowered or "loading ohlcv" in lowered:
        return "Scanning NSE universe..."
    if "done. loaded from cache" in lowered:
        return "Technical scan completed. Preparing AI review..."
    if "llm gate" in lowered:
        return "Selecting top-ranked stocks for AI review..."
    if "grok" in lowered:
        return "AI review is checking the selected stocks..."
    if "gemini" in lowered:
        return "AI review is checking the selected stocks..."
    if "phase ohlcv-bulk-load started" in lowered:
        return "Loading one-year price history from database..."
    if "phase ohlcv-bulk-load completed" in lowered:
        return "Price history loaded. Filtering NSE universe..."
    if "phase technical-scan started" in lowered:
        return "Filtering technical and news-driven candidates..."
    if "phase technical-scan completed" in lowered:
        return "Candidate filtering completed. Preparing AI review..."
    if "phase llm-validation started" in lowered:
        return "Validating selected stocks with AI..."
    if "phase llm-validation completed" in lowered:
        return "AI review completed. Saving the report..."
    if "phase save-breakout-log started" in lowered:
        return "Saving scan results..."
    if "results:" in lowered:
        return "Finalizing recommended stocks..."
    if "html report saved" in lowered:
        return "Report generated successfully."
    if "scanner completed" in lowered or "daily scan completed" in lowered:
        return "Scan completed."
    if "scanner failed" in lowered or "traceback" in lowered or "error" in lowered or "exception" in lowered:
        return "Scan failed. Please check backend logs for technical details."
    if clean.startswith("[") or "=" in clean or "model=" in lowered:
        return fallback
    return fallback


@dataclass
class ScanJob:
    id: str
    user_email: str | None = None
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
        _log_scan_line(self.id, clean)
        self.lines.append(clean)
        if len(self.lines) > 2000:
            self.lines = self.lines[-2000:]
        self.line_queue.put(clean)
        self.message = public_message(clean, self.message)
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

    grok_match = re.search(r"grok\]\s+evaluating batch\s+(\d+)(?:\s+of\s+(\d+))?", lowered)
    if grok_match:
        batch = int(grok_match.group(1))
        total = int(grok_match.group(2) or batch)
        return min(88, 74 + int((batch / max(1, total)) * 14))

    gemini_match = re.search(r"gemini\s+(\d+)\s*/\s*(\d+)", lowered)
    if gemini_match:
        done = int(gemini_match.group(1))
        total = int(gemini_match.group(2))
        return min(88, 74 + int((done / max(1, total)) * 14))

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

    def start_scan(self, scan_date: str | None = None, force_refresh: bool = False, user_email: str | None = None) -> ScanJob:
        with self._lock:
            for job in self._jobs.values():
                if job.status in {"queued", "running"}:
                    return job

            job_id = uuid.uuid4().hex[:12]
            command = [scanner_python(), "scanner_main.py", "scan"]
            if scan_date:
                command.extend(["--date", scan_date])
            if force_refresh:
                command.append("--force-refresh")
            job = ScanJob(id=job_id, command=command, user_email=user_email)
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
        settings = app_settings(job.user_email)
        env["LLM_VALIDATION_LIMIT"] = str(settings["llm_validation_limit"])
        env["REPORT_INCLUDE_WEAK"] = "true" if settings["report_include_weak"] else "false"
        env["TRADINGVIEW_CHART_ID"] = settings["tradingview_chart_id"]
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
                detail = _last_useful_error(job.lines)
                suffix = f" Last error: {detail}" if detail else ""
                job.append(f"Scanner failed with exit code {job.exit_code}.{suffix}")
                job.message = "Scan failed. Please check backend logs for technical details."
        except Exception as exc:
            job.status = "failed"
            job.ended_at = datetime.now().isoformat(timespec="seconds")
            job.exit_code = -1
            job.append(f"Scanner failed: {exc}")
            job.message = "Scan failed. Please check backend logs for technical details."

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
    if not (AGENT_ROOT / "scanner_main.py").exists():
        raise RuntimeError(f"Scanner project root not found: {AGENT_ROOT}")
    return AGENT_ROOT
