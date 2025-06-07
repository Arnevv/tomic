"""Simple RPC helper for the prototype TWS daemon."""

from __future__ import annotations

import json
from multiprocessing import Queue
from pathlib import Path
from uuid import uuid4
from datetime import datetime

TASK_QUEUE: Queue = Queue()

JOBS_DIR = Path("jobs")
JOBS_DIR.mkdir(exist_ok=True)
STATUS_DIR = JOBS_DIR / "status"
STATUS_DIR.mkdir(exist_ok=True)
INDEX_FILE = JOBS_DIR / "index.json"
if not INDEX_FILE.exists():
    INDEX_FILE.write_text("[]")


def _load_index() -> list[dict]:
    try:
        return json.loads(INDEX_FILE.read_text())
    except Exception:  # pragma: no cover - corrupt file
        return []


def _save_index(entries: list[dict]) -> None:
    INDEX_FILE.write_text(json.dumps(entries, indent=2))


def get_entry(job_id: str) -> dict | None:
    for entry in _load_index():
        if entry.get("job_id") == job_id:
            return entry
    return None


def update_index(job_id: str, **updates: object) -> dict | None:
    entries = _load_index()
    for entry in entries:
        if entry.get("job_id") == job_id:
            for key, val in updates.items():
                if val is not None:
                    entry[key] = val
            _save_index(entries)
            return entry
    return None


def increment_retries(job_id: str) -> int:
    entries = _load_index()
    for entry in entries:
        if entry.get("job_id") == job_id:
            entry["retries"] = entry.get("retries", 0) + 1
            _save_index(entries)
            return entry["retries"]
    return 0


def load_index() -> list[dict]:
    """Return current list of all job entries."""
    return _load_index()


def submit_task(task: dict) -> str:
    """Queue a task for the :class:`TwsSessionManager` daemon."""
    job_id = task.get("id") or uuid4().hex
    task["id"] = job_id
    TASK_QUEUE.put(task)
    job_file = JOBS_DIR / f"{job_id}.json"
    job_file.write_text(json.dumps(task))
    ts = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    status_file = STATUS_DIR / f"{job_id}.json"
    status_file.write_text(
        json.dumps({"state": "queued", "updated": ts, "progress": None, "error": None})
    )
    entries = _load_index()
    entries.append(
        {
            "job_id": job_id,
            "type": task.get("type"),
            "symbol": task.get("symbol"),
            "created": ts,
            "status": "queued",
            "retries": 0,
            "max_retries": task.get("max_retries", 0),
            "task": task,
        }
    )
    _save_index(entries)
    return job_id


def retry_job(job_id: str) -> bool:
    """Requeue job ``job_id`` from the index."""
    entry = get_entry(job_id)
    if not entry:
        return False
    task = entry.get("task")
    if not task:
        return False
    TASK_QUEUE.put(task)
    job_file = JOBS_DIR / f"{job_id}.json"
    job_file.write_text(json.dumps(task))
    ts = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    status_file = STATUS_DIR / f"{job_id}.json"
    status_file.write_text(
        json.dumps({"state": "queued", "updated": ts, "progress": None, "error": None})
    )
    update_index(job_id, status="queued", updated=ts)
    return True
