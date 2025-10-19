from __future__ import annotations

"""Services for fetching implied volatility data via Polygon."""

from datetime import datetime
from pathlib import Path
from time import sleep
from typing import Sequence

from tomic.config import get as cfg_get
from tomic.helpers.price_utils import _load_latest_close
from tomic.infrastructure.storage import load_json, update_json_file
from tomic.infrastructure.throttling import RateLimiter
from tomic.logutils import logger
from tomic.providers.polygon_iv import fetch_polygon_iv30d


def fetch_polygon_iv_data(symbols: Sequence[str] | None = None) -> list[str]:
    """Fetch and store Polygon IV metrics for ``symbols``."""
    configured = cfg_get("DEFAULT_SYMBOLS", [])
    target_symbols = [s.upper() for s in symbols] if symbols else [s.upper() for s in configured]
    if not target_symbols:
        logger.warning("No symbols configured for Polygon IV fetch")
        return []

    summary_dir = Path(cfg_get("IV_DAILY_SUMMARY_DIR", "tomic/data/iv_daily_summary"))
    raw_max = cfg_get("MAX_SYMBOLS_PER_RUN")
    try:
        max_syms = int(raw_max) if raw_max is not None else None
    except (TypeError, ValueError):
        max_syms = None
    sleep_between = float(cfg_get("POLYGON_SLEEP_BETWEEN", 1.2))

    processed = 0
    stored: list[str] = []
    limiter = RateLimiter(1, sleep_between, sleep=sleep)
    for sym in target_symbols:
        limiter.wait()
        if max_syms is not None and processed >= max_syms:
            break
        metrics = fetch_polygon_iv30d(sym)
        date_str = _load_latest_close(sym, return_date_only=True) or datetime.now().strftime(
            "%Y-%m-%d"
        )
        if metrics is None:
            logger.warning(f"No contracts found for symbol {sym}")
            processed += 1
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
            continue

        try:
            update_json_file(file, record, ["date"])
            logger.info(f"Saved IV for {sym}")
            stored.append(sym)
        except Exception as exc:  # pragma: no cover - filesystem errors
            logger.warning(f"Failed to save IV for {sym}: {exc}")
        processed += 1

    if stored:
        logger.success("✅ Polygon IV fetch complete")
    else:
        logger.warning("⚠️ Geen Polygon IV-data opgeslagen")
    return stored
