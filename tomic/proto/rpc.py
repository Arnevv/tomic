"""Simple RPC helper for the prototype TWS daemon."""

from __future__ import annotations

import json
from multiprocessing import Queue
from pathlib import Path

TASK_QUEUE: Queue = Queue()

JOBS_DIR = Path("jobs")
JOBS_DIR.mkdir(exist_ok=True)


def submit_task(task: dict) -> None:
    """Queue a task for the :class:`TwsSessionManager` daemon."""
    TASK_QUEUE.put(task)
    ts = task.get("timestamp")
    symbol = task.get("symbol", "task")
    if ts is None:
        from datetime import datetime

        ts = datetime.now().strftime("%Y%m%d%H%M%S")
    job_file = JOBS_DIR / f"{symbol}_{ts}.json"
    job_file.write_text(json.dumps(task))
