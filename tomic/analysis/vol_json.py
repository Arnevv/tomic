from __future__ import annotations

"""Helpers for working with volatility data stored as JSON."""

from pathlib import Path
from types import SimpleNamespace
from typing import Iterable, Dict, Any

from tomic.config import get as cfg_get
from tomic.journal.utils import load_json


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
