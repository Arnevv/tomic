from __future__ import annotations

"""Fetch upcoming earnings dates using the Alpha Vantage API."""

import csv
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List

import requests

from tomic.config import get as cfg_get
from tomic.logutils import logger, setup_logging
from tomic.journal.utils import load_json, save_json


def _parse_dates(csv_text: str) -> List[str]:
    """Return report dates in ``YYYY-MM-DD`` format from Alpha Vantage CSV."""
    reader = csv.DictReader(csv_text.splitlines())
    dates: List[str] = []
    for row in reader:
        rep_date = row.get("reportDate")
        if rep_date:
            dates.append(rep_date)
    return dates


def _fetch_symbol(symbol: str, api_key: str) -> List[str]:
    """Return upcoming earnings dates for ``symbol``."""
    url = (
        "https://www.alphavantage.co/query?function=EARNINGS_CALENDAR"
        f"&symbol={symbol}&horizon=6month&apikey={api_key}"
    )
    logger.debug(f"Requesting {url}")
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return _parse_dates(resp.text)


def _merge_dates(existing: List[str], new: List[str]) -> List[str]:
    """Return merged list with updated upcoming dates."""
    today = date.today()
    existing_dates = [datetime.strptime(d, "%Y-%m-%d").date() for d in existing]
    new_dates = [datetime.strptime(d, "%Y-%m-%d").date() for d in new]

    past = [d for d in existing_dates if d < today]
    upcoming = [d for d in existing_dates if d >= today]

    updated: List[date] = []
    used_new: set[date] = set()
    for old in upcoming:
        match = None
        for nd in new_dates:
            if abs((nd - old).days) <= 7:
                match = nd
                used_new.add(nd)
                break
        if match:
            updated.append(match)

    for nd in new_dates:
        if nd not in used_new:
            updated.append(nd)

    all_dates = sorted(set(updated + past), reverse=True)
    return [d.strftime("%Y-%m-%d") for d in all_dates]


def main(argv: List[str] | None = None) -> None:
    """Fetch and update earnings dates for configured symbols."""
    setup_logging()
    logger.info("\U0001F680 Earnings dates fetch")
    api_key = cfg_get("ALPHAVANTAGE_API_KEY", "")
    if not api_key:
        logger.error("Missing ALPHAVANTAGE_API_KEY in configuration")
        return

    symbols = [s.upper() for s in cfg_get("DEFAULT_SYMBOLS", [])]
    earnings_file = Path(cfg_get("EARNINGS_DATES_FILE", "tomic/data/earnings_dates.json"))
    data = load_json(earnings_file)
    if not isinstance(data, dict):
        data = {}

    stored = 0
    with TemporaryDirectory() as _tmp:
        for sym in symbols:
            try:
                dates = _fetch_symbol(sym, api_key)
            except Exception as exc:  # pragma: no cover - network errors
                logger.error(f"Failed to fetch {sym}: {exc}")
                continue
            if not dates:
                continue
            current = data.get(sym, []) if isinstance(data.get(sym), list) else []
            data[sym] = _merge_dates(current, dates)
            stored += 1

    save_json(data, earnings_file)
    logger.success(f"✅ Earnings dates updated for {stored} symbols")


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
