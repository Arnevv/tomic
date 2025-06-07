"""Prototype daemon managing a single TWS connection."""

from __future__ import annotations

import json
import time
from multiprocessing import Process
from queue import Empty

from tomic.logging import logger
from tomic.config import get as cfg_get
from tomic.api.market_export import export_market_data

from . import rpc


class TwsSessionManager:
    """Singleton process that handles TWS tasks."""

    _instance: "TwsSessionManager | None" = None

    def __init__(self) -> None:
        self.process = Process(target=self._run, daemon=True)
        self.process.start()

    @classmethod
    def instance(cls) -> "TwsSessionManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _update_status(self, job_id: str, state: str) -> None:
        status_file = rpc.STATUS_DIR / f"{job_id}.json"
        try:
            status_file.write_text(json.dumps({"state": state}))
        except Exception as exc:  # pragma: no cover - unlikely
            logger.error(f"Kan status niet schrijven: {exc}")

    def _run(self) -> None:
        jobs_dir = rpc.JOBS_DIR
        logger.info("TwsSessionManager gestart")
        while True:
            task = None
            source_file = None
            try:
                task = rpc.TASK_QUEUE.get_nowait()
            except Empty:
                for job_file in jobs_dir.glob("*.json"):
                    try:
                        data = json.loads(job_file.read_text())
                    except Exception as exc:
                        logger.error(f"Ongeldig jobbestand {job_file}: {exc}")
                        job_file.unlink()
                        continue
                    task = data
                    source_file = job_file
                    break
                if task is None:
                    time.sleep(0.5)
                    continue

            job_id = task.get("id")
            if job_id:
                self._update_status(job_id, "running")
            try:
                self._handle_task(task)
            except Exception:
                logger.exception("Taak mislukt: %s", task)
                if job_id:
                    self._update_status(job_id, "failed")
            else:
                if job_id:
                    self._update_status(job_id, "completed")
            if source_file:
                source_file.unlink()

    def _handle_task(self, task: dict) -> None:
        typ = task.get("type")
        if typ == "get_market_data":
            symbol = task.get("symbol")
            output_dir = task.get("output_dir") or cfg_get("EXPORT_DIR", "exports")
            if not symbol:
                logger.error("Ontbrekend symbool in taak")
                return
            logger.info(f"Export market data voor {symbol}")
            export_market_data(symbol, output_dir)
        else:
            logger.warning(f"Onbekende taak: {task}")


def main() -> None:
    """Start the TWS session daemon."""
    TwsSessionManager.instance()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("TwsSessionManager gestopt")


if __name__ == "__main__":
    main()
