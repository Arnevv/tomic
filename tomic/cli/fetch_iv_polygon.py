from __future__ import annotations

"""Fetch and store daily implied volatility using Polygon."""

from datetime import datetime
from pathlib import Path
from typing import List

from tomic.config import get as cfg_get
from tomic.logutils import logger, setup_logging
from tomic.journal.utils import update_json_file
from tomic.providers.polygon_iv import fetch_polygon_iv30d


def main(argv: List[str] | None = None) -> None:
    """Fetch IV for configured symbols using Polygon."""
    setup_logging()
    logger.info("🚀 Fetching IV data via Polygon")
    if argv is None:
        argv = []
    symbols = [s.upper() for s in argv] if argv else [s.upper() for s in cfg_get("DEFAULT_SYMBOLS", [])]
    summary_dir = Path(cfg_get("IV_DAILY_SUMMARY_DIR", "tomic/data/iv_daily_summary"))
    today = datetime.now().strftime("%Y-%m-%d")

    for sym in symbols:
        iv = fetch_polygon_iv30d(sym)
        record = {
            "date": today,
            "atm_iv": iv,
            "iv_rank": None,
            "iv_percentile": None,
        }
        try:
            update_json_file(summary_dir / f"{sym}.json", record, ["date"])
            logger.info(f"Saved IV for {sym}")
        except Exception as exc:  # pragma: no cover - filesystem errors
            logger.warning(f"Failed to save IV for {sym}: {exc}")
    logger.success("✅ Polygon IV fetch complete")


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
