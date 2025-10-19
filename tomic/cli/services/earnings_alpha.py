from __future__ import annotations

"""Services for fetching earnings data via Alpha Vantage."""

import csv
import os
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from time import sleep
from typing import Iterable, Sequence

import requests

from tomic.config import get as cfg_get
from tomic.helpers.dateutils import parse_date
from tomic.infrastructure.storage import load_json, save_json
from tomic.infrastructure.throttling import RateLimiter
from tomic.logutils import logger


def _parse_dates(csv_text: str) -> list[str]:
    """Return report dates in ``YYYY-MM-DD`` format from Alpha Vantage CSV."""
    reader = csv.DictReader(csv_text.splitlines())
    dates: list[str] = []
    for row in reader:
        rep_date = row.get("reportDate")
        if rep_date:
            dates.append(rep_date)
    return dates


def _fetch_symbol(symbol: str, api_key: str) -> list[str]:
    """Return upcoming earnings dates for ``symbol``."""
    url = (
        "https://www.alphavantage.co/query?function=EARNINGS_CALENDAR"
        f"&symbol={symbol}&horizon=6month&apikey={api_key}"
    )
    logger.debug(f"Requesting {url}")
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return _parse_dates(resp.text)


def _safe_parse_date(raw: str) -> date | None:
    parsed = parse_date(raw)
    if parsed is None:
        logger.warning(f"⚠️ Ongeldige datum overgeslagen: {raw}")
    return parsed


def _merge_dates(existing: Iterable[str], new: Iterable[str]) -> list[str]:
    """Return merged list with updated upcoming dates."""
    today = date.today()
    existing_dates = [d for d in (_safe_parse_date(x) for x in existing) if d]
    new_dates = [d for d in (_safe_parse_date(x) for x in new) if d]

    past = [d for d in existing_dates if d < today]
    upcoming = [d for d in existing_dates if d >= today]

    updated: list[date] = []
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


def update_alpha_earnings(symbols: Sequence[str] | None = None) -> list[str]:
    """Fetch and update earnings dates for ``symbols``."""
    configured = cfg_get("DEFAULT_SYMBOLS", [])
    target_symbols = [s.upper() for s in symbols] if symbols else [s.upper() for s in configured]
    api_key = cfg_get("ALPHAVANTAGE_API_KEY", "") or os.environ.get("ALPHAVANTAGE_API_KEY", "")
    if not api_key:
        logger.error("Missing ALPHAVANTAGE_API_KEY in configuration")
        return []
    if not target_symbols:
        logger.warning("No symbols configured for Alpha Vantage earnings fetch")
        return []

    sleep_between = float(cfg_get("ALPHAVANTAGE_SLEEP_BETWEEN", 12.0))
    earnings_file = Path(cfg_get("EARNINGS_DATES_FILE", "tomic/data/earnings_dates.json"))
    meta_file = Path(cfg_get("EARNINGS_DATA_FILE", "tomic/data/earnings_data.json"))

    data = load_json(earnings_file)
    if not isinstance(data, dict):
        data = {}
    meta = load_json(meta_file)
    if not isinstance(meta, dict):
        meta = {}

    for sym in target_symbols:
        data.setdefault(sym, [])
        meta.setdefault(sym, "")

    def _last_seen(sym: str) -> datetime:
        ts = meta.get(sym)
        if isinstance(ts, str):
            try:
                return datetime.fromisoformat(ts)
            except ValueError:
                pass
        return datetime.fromtimestamp(0)

    sorted_symbols = sorted(target_symbols, key=_last_seen)

    stored = 0
    limiter = RateLimiter(1, sleep_between, sleep=sleep)
    with TemporaryDirectory() as _tmp:
        for sym in sorted_symbols:
            limiter.wait()
            try:
                dates = _fetch_symbol(sym, api_key)
                logger.info(f"{sym} new dates from API: {dates}")
            except Exception as exc:  # pragma: no cover - network errors
                logger.error(f"Failed to fetch {sym}: {exc}")
                continue
            if not dates:
                logger.warning(
                    f"⚠️ Geen earnings data voor {sym}, mogelijk API-probleem."
                )
                continue

            current = data.get(sym, []) if isinstance(data.get(sym), list) else []
            merged = _merge_dates(current, dates)
            if not merged and current:
                logger.warning(
                    f"⚠️ Merge resulteerde in lege lijst voor {sym}, hou oude data aan."
                )
                data[sym] = current
            elif len(merged) < len(current):
                logger.warning(
                    f"⚠️ Merge voor {sym} lijkt regressie te bevatten ({len(merged)} < {len(current)}), oude data behouden."
                )
                data[sym] = current
            elif set(merged).issubset(set(current)):
                logger.warning(
                    f"⚠️ Merge voor {sym} voegt niets toe, hou oude data aan."
                )
                data[sym] = current
            else:
                data[sym] = merged
                stored += 1
                meta[sym] = datetime.now().isoformat()

    save_json(data, earnings_file)
    save_json(meta, meta_file)
    if stored:
        logger.success(f"✅ Earnings dates updated for {stored} symbols")
    else:
        logger.warning("⚠️ Geen earnings-updates weggeschreven")
    return [sym for sym in sorted_symbols if sym in data]
