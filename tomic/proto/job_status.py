from __future__ import annotations

import json
import sys

from .rpc import STATUS_DIR


def job_status(job_id: str) -> str | None:
    path = STATUS_DIR / f"{job_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except Exception:
        return None
    return data.get("state")


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    if not argv:
        print("Usage: job_status JOB_ID")
        return 1
    state = job_status(argv[0])
    if state is None:
        print("Unknown job")
        return 1
    print(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
