"""Command line tools to interact with the TWS daemon."""
from __future__ import annotations

import argparse
import json
from typing import Any

from tomic.logging import setup_logging, logger
from tomic.proto import rpc

try:
    from tabulate import tabulate
except Exception:  # pragma: no cover - fallback
    def tabulate(rows: list[list[Any]], headers: list[str] | None = None) -> str:
        if headers:
            rows = [headers] + rows
        col_w = [max(len(str(c)) for c in col) for col in zip(*rows)]
        def fmt(row: list[Any]) -> str:
            return " | ".join(str(c).ljust(col_w[i]) for i, c in enumerate(row))
        return "\n".join(fmt(r) for r in rows)


def _load_status(job_id: str) -> dict:
    path = rpc.STATUS_DIR / f"{job_id}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def cmd_status(_args: argparse.Namespace) -> None:
    jobs = rpc.load_index()
    counts: dict[str, int] = {}
    for j in jobs:
        counts[j.get("status", "?")] = counts.get(j.get("status", "?"), 0) + 1
    for status, count in counts.items():
        print(f"{status}: {count}")


def cmd_ls(args: argparse.Namespace) -> None:
    jobs = rpc.load_index()
    rows = []
    for j in jobs:
        if not args.all and j.get("status") not in {"queued", "running"}:
            continue
        rows.append(
            [
                j.get("job_id"),
                j.get("type"),
                j.get("symbol"),
                j.get("status"),
                j.get("retries", 0),
            ]
        )
    print(tabulate(rows, headers=["ID", "Type", "Symbol", "Status", "Retries"]))


def cmd_show(args: argparse.Namespace) -> int:
    entry = rpc.get_entry(args.job_id)
    if not entry:
        print("Unknown job")
        return 1
    status = _load_status(args.job_id)
    print(json.dumps({"index": entry, "status": status}, indent=2))
    return 0


def cmd_retry(args: argparse.Namespace) -> int:
    if rpc.retry_job(args.job_id):
        print("requeued")
        return 0
    print("unknown job")
    return 1


def cmd_purge(args: argparse.Namespace) -> None:
    jobs = rpc.load_index()
    kept = []
    for j in jobs:
        if args.failed and j.get("status") == "failed":
            (rpc.STATUS_DIR / f"{j['job_id']}.json").unlink(missing_ok=True)
            (rpc.JOBS_DIR / f"{j['job_id']}.json").unlink(missing_ok=True)
        else:
            kept.append(j)
    rpc._save_index(kept)  # type: ignore[attr-defined]


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    parser = argparse.ArgumentParser("daemonctl")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("status").set_defaults(func=cmd_status)

    ls_p = sub.add_parser("ls", help="List jobs")
    ls_p.add_argument("--all", action="store_true")
    ls_p.set_defaults(func=cmd_ls)

    show_p = sub.add_parser("show", help="Show job details")
    show_p.add_argument("job_id")
    show_p.set_defaults(func=cmd_show)

    ret_p = sub.add_parser("retry", help="Retry a job")
    ret_p.add_argument("job_id")
    ret_p.set_defaults(func=cmd_retry)

    purge_p = sub.add_parser("purge", help="Purge jobs")
    purge_p.add_argument("--failed", action="store_true")
    purge_p.set_defaults(func=cmd_purge)

    args = parser.parse_args(argv)
    if hasattr(args, "func"):
        return args.func(args) or 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
