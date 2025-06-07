"""Simple RPC helper for the prototype TWS daemon."""

from __future__ import annotations

import json
from multiprocessing import Queue
from pathlib import Path
from uuid import uuid4

TASK_QUEUE: Queue = Queue()

JOBS_DIR = Path("jobs")
JOBS_DIR.mkdir(exist_ok=True)
STATUS_DIR = JOBS_DIR / "status"
STATUS_DIR.mkdir(exist_ok=True)


def submit_task(task: dict) -> str:
    """Queue a task for the :class:`TwsSessionManager` daemon."""
    job_id = task.get("id") or uuid4().hex
    task["id"] = job_id
    TASK_QUEUE.put(task)
    job_file = JOBS_DIR / f"{job_id}.json"
    job_file.write_text(json.dumps(task))
    status_file = STATUS_DIR / f"{job_id}.json"
    status_file.write_text(json.dumps({"state": "queued"}))
    return job_id
