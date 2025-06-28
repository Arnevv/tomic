from __future__ import annotations

"""Helpers for working with volatility data stored as JSON."""

from pathlib import Path
from types import SimpleNamespace
from typing import Iterable, Dict, Any

from tomic.config import get as cfg_get
from tomic.journal.utils import load_json, update_json_file
from tomic.logutils import logger


DEFAULT_SUMMARY_DIR = Path(cfg_get("IV_DAILY_SUMMARY_DIR", "tomic/data/iv_daily_summary"))


def _load_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = load_json(path)
    return list(data) if isinstance(data, list) else []


def get_latest_summary(symbol: str, base_dir: Path | None = None) -> SimpleNamespace | None:
    """Return latest IV summary record for ``symbol`` or ``None``."""
    if base_dir is None:
        base_dir = DEFAULT_SUMMARY_DIR
    path = base_dir / f"{symbol}.json"
    records = _load_records(path)
    if not records:
        return None
    records.sort(key=lambda r: r.get("date", ""))
    return SimpleNamespace(**records[-1])


def load_latest_summaries(symbols: Iterable[str], base_dir: Path | None = None) -> Dict[str, SimpleNamespace]:
    """Return mapping of symbol to latest IV summary record."""
    result: Dict[str, SimpleNamespace] = {}
    for sym in symbols:
        rec = get_latest_summary(sym, base_dir)
        if rec is not None:
            result[sym] = rec
    return result


def append_to_iv_summary(
    symbol: str, record: Dict[str, Any], base_dir: Path | None = None
) -> None:
    """Safely append ``record`` to the daily IV summary for ``symbol``."""

    if base_dir is None:
        base_dir = DEFAULT_SUMMARY_DIR

    path = Path(base_dir) / f"{symbol}.json"
    path.parent.mkdir(parents=True, exist_ok=True)

    if not isinstance(record, dict):
        logger.error(f"Invalid record for {symbol}: {record!r}")
        return

    if all(record.get(k) is None for k in record if k != "date"):
        logger.error(f"Skipping summary write for {symbol}; record has no data")
        return

    try:
        update_json_file(path, record, ["date"])
    except Exception as exc:  # pragma: no cover - filesystem errors
        logger.error(f"Failed to update IV summary for {symbol}: {exc}")
        return

    logger.info(f"IV summary updated for {symbol} at {path}")
