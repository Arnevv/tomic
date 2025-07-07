from __future__ import annotations

import math
import statistics
from datetime import timedelta
from pathlib import Path
from typing import Iterable, List

from tomic.config import get as cfg_get
from tomic.journal.utils import load_json, save_json
from tomic.logutils import logger, setup_logging
from tomic.utils import today


def _load_price_data(symbol: str) -> list[tuple[str, float]]:
    """Return list of (date, close) tuples sorted by date."""
    base = Path(cfg_get("PRICE_HISTORY_DIR", "tomic/data/spot_prices"))
    path = base / f"{symbol}.json"
    data = load_json(path)
    records: list[tuple[str, float]] = []
    if isinstance(data, list):
        for rec in data:
            d = rec.get("date")
            c = rec.get("close")
            if d is None or c is None:
                continue
            try:
                records.append((str(d), float(c)))
            except Exception:
                continue
    records.sort(key=lambda r: r[0])
    return records


def _load_existing_hv(symbol: str) -> tuple[list[dict], Path]:
    base = Path(cfg_get("HISTORICAL_VOLATILITY_DIR", "tomic/data/historical_volatility"))
    path = base / f"{symbol}.json"
    data = load_json(path)
    records = list(data) if isinstance(data, list) else []
    records.sort(key=lambda r: r.get("date", ""))
    return records, path


def _calculate_hv(closes: list[float]) -> list[dict]:
    returns = [math.log(c2 / c1) for c1, c2 in zip(closes[:-1], closes[1:])]
    results = []
    for i in range(1, len(closes)):
        rec: dict[str, float | None] = {}
        if i >= 20:
            rec["hv20"] = statistics.stdev(returns[i-20:i]) * math.sqrt(252)
        if i >= 30:
            rec["hv30"] = statistics.stdev(returns[i-30:i]) * math.sqrt(252)
        if i >= 90:
            rec["hv90"] = statistics.stdev(returns[i-90:i]) * math.sqrt(252)
        if i >= 252:
            rec["hv252"] = statistics.stdev(returns[i-252:i]) * math.sqrt(252)
        results.append(rec)
    return results


def _save_hv(symbol: str, new_data: Iterable[dict]) -> None:
    base = Path(cfg_get("HISTORICAL_VOLATILITY_DIR", "tomic/data/historical_volatility"))
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{symbol}.json"
    existing = load_json(path)
    data = list(existing) if isinstance(existing, list) else []
    data.extend(new_data)
    data.sort(key=lambda r: r.get("date", ""))
    save_json(data, path)


def run_backfill_hv(symbols: List[str] | None = None) -> None:
    setup_logging()
    logger.info("🚀 Backfilling historical volatility")
    if symbols is None:
        symbols = [s.upper() for s in cfg_get("DEFAULT_SYMBOLS", [])]
    end_date = today()
    for sym in symbols:
        price_records = _load_price_data(sym)
        if not price_records:
            logger.warning(f"⚠️ Geen prijsdata voor {sym}")
            continue
        dates, closes = zip(*price_records)
        hv_data, path = _load_existing_hv(sym)
        existing_dates = {rec.get("date") for rec in hv_data}
        if hv_data:
            last_date = hv_data[-1]["date"]
            start_idx = dates.index(last_date) + 1 if last_date in dates else 0
        else:
            start_idx = 252
        new_records: list[dict] = []
        hv_values = _calculate_hv(list(closes))
        for idx in range(start_idx, len(dates)):
            date_str = dates[idx]
            if date_str > end_date.strftime("%Y-%m-%d"):
                break
            rec = hv_values[idx-1]
            if "hv252" not in rec:
                logger.warning(f"⚠️ {sym}: te weinig spotdata voor hv252 op {date_str}")
                continue
            if date_str in existing_dates:
                continue
            new_records.append({
                "date": date_str,
                "hv20": round(rec["hv20"], 9),
                "hv30": round(rec["hv30"], 9),
                "hv90": round(rec["hv90"], 9),
                "hv252": round(rec["hv252"], 9),
            })
        if new_records:
            _save_hv(sym, new_records)
            logger.success(
                f"✅ Backfilled HV voor {sym}: {new_records[0]['date']} → {new_records[-1]['date']} ({len(new_records)} records toegevoegd)"
            )
        else:
            logger.info(f"⏭️ {sym}: geen nieuwe HV-records")
