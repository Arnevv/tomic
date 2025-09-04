from __future__ import annotations

"""Fetch and store daily implied volatility using Polygon."""

from datetime import datetime
from pathlib import Path
from time import sleep
from typing import List

from tomic.config import get as cfg_get
from tomic.logutils import logger, setup_logging
from tomic.journal.utils import load_json, update_json_file
from tomic.providers.polygon_iv import fetch_polygon_iv30d
from tomic.helpers.price_utils import _load_latest_close


def main(argv: List[str] | None = None) -> None:
    """Fetch IV for configured symbols using Polygon."""
    setup_logging()
    logger.info("🚀 Fetching IV data via Polygon")
    if argv is None:
        argv = []
    symbols = [s.upper() for s in argv] if argv else [s.upper() for s in cfg_get("DEFAULT_SYMBOLS", [])]
    summary_dir = Path(cfg_get("IV_DAILY_SUMMARY_DIR", "tomic/data/iv_daily_summary"))
    raw_max = cfg_get("MAX_SYMBOLS_PER_RUN")
    try:
        max_syms = int(raw_max) if raw_max is not None else None
    except (TypeError, ValueError):
        max_syms = None
    sleep_between = float(cfg_get("POLYGON_SLEEP_BETWEEN", 1.2))

    processed = 0
    for sym in symbols:
        if max_syms is not None and processed >= max_syms:
            break
        metrics = fetch_polygon_iv30d(sym)
        date_str = _load_latest_close(sym, return_date_only=True) or datetime.now().strftime(
            "%Y-%m-%d"
        )
        if metrics is None:
            logger.warning(f"No contracts found for symbol {sym}")
            continue
        iv = metrics.get("atm_iv")
        record = {
            "date": date_str,
            "atm_iv": iv,
            "iv_rank": None,
            "iv_percentile": None,
        }

        file = summary_dir / f"{sym}.json"
        existing = load_json(file)
        if any(
            isinstance(r, dict)
            and r.get("date") == date_str
            and r.get("atm_iv") is not None
            for r in existing
        ):
            logger.info(f"⏭️ {sym} al aanwezig voor {date_str}")
            processed += 1
            sleep(sleep_between)
            continue

        try:
            update_json_file(file, record, ["date"])
            logger.info(f"Saved IV for {sym}")
        except Exception as exc:  # pragma: no cover - filesystem errors
            logger.warning(f"Failed to save IV for {sym}: {exc}")
        processed += 1
        sleep(sleep_between)
    logger.success("✅ Polygon IV fetch complete")


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
