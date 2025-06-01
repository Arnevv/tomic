"""Utilities for storing daily volatility snapshots."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List

from tomic.logging import logger
from tomic.config import get as cfg_get


def store_volatility_snapshot(
    symbol_data: Dict[str, Any], output_path: str | None = None
) -> None:
    """Append a volatility snapshot to a JSON file if data is complete."""
    if output_path is None:
        output_path = cfg_get("VOLATILITY_DATA_FILE", "volatility_data.json")

    required = ["date", "symbol", "spot", "iv30", "hv30", "iv_rank", "skew"]
    missing = [key for key in required if symbol_data.get(key) is None]
    if missing:
        logger.warning(
            f"Incomplete snapshot for {symbol_data.get('symbol')} skipped: missing {', '.join(missing)}"
        )
        return

    file = Path(output_path)
    if file.exists():
        with open(file, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = []

    # remove existing entry for same symbol and date
    data = [
        d
        for d in data
        if not (
            d.get("symbol") == symbol_data["symbol"]
            and d.get("date") == symbol_data["date"]
        )
    ]
    data.append(symbol_data)

    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def snapshot_symbols(
    symbols: List[str],
    fetcher: Callable[[str], Dict[str, Any]],
    output_path: str | None = None,
) -> None:
    """Take a volatility snapshot for each symbol using the given fetcher."""
    for sym in symbols:
        logger.info(f"Fetching metrics for {sym}")
        try:
            metrics = fetcher(sym)
        except Exception as exc:  # pragma: no cover - network dependent
            logger.error(f"Failed for {sym}: {exc}")
            continue
        record = {
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "symbol": sym,
            "spot": metrics.get("spot_price"),
            "iv30": metrics.get("implied_volatility"),
            "hv30": metrics.get("hv30"),
            "iv_rank": metrics.get("iv_rank"),
            "skew": metrics.get("skew"),
        }
        store_volatility_snapshot(record, output_path)
        logger.info(f"Stored snapshot for {sym}")


__all__ = ["store_volatility_snapshot", "snapshot_symbols"]
