from __future__ import annotations
from pathlib import Path
from typing import Iterable, List

from tomic.analysis.metrics import historical_volatility
from tomic.config import get as cfg_get
from tomic.journal.utils import load_json, save_json
from tomic.logutils import logger, setup_logging
from tomic.utils import today, load_price_history

WINDOWS = (20, 30, 90, 252)


def _load_price_data(symbol: str) -> list[tuple[str, float]]:
    """Return list of (date, close) tuples sorted by date."""
    records: list[tuple[str, float]] = []
    for rec in load_price_history(symbol):
        d = rec.get("date")
        c = rec.get("close")
        if d is None or c is None:
            continue
        try:
            records.append((str(d), float(c)))
        except Exception:
            continue
    return records


def _load_existing_hv(symbol: str) -> tuple[list[dict], Path]:
    base = Path(cfg_get("HISTORICAL_VOLATILITY_DIR", "tomic/data/historical_volatility"))
    path = base / f"{symbol}.json"
    data = load_json(path)
    records = list(data) if isinstance(data, list) else []
    records.sort(key=lambda r: r.get("date", ""))
    return records, path


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

        if len(dates) != len(set(dates)):
            logger.error(f"❌ {sym}: dubbele datums in spotprijsdata")
            continue

        max_window = max(WINDOWS)
        if len(dates) <= max_window:
            logger.warning(f"⚠️ {sym}: te weinig spotdata (<{max_window} dagen)")
            continue

        start_idx = max_window
        new_records: list[dict] = []
        end_str = end_date.strftime("%Y-%m-%d")
        for idx in range(start_idx, len(dates)):
            date_str = dates[idx]
            if date_str > end_str:
                break
            if date_str in existing_dates:
                continue
            rec: dict[str, float | str] = {"date": date_str}
            for window in WINDOWS:
                hv = historical_volatility(closes[: idx + 1], window=window)
                if hv is not None:
                    rec[f"hv{window}"] = round(hv / 100, 9)
            if rec.get("hv252") is None:
                logger.warning(f"⚠️ {sym}: te weinig spotdata voor hv252 op {date_str}")
                continue
            new_records.append(rec)
        if new_records:
            _save_hv(sym, new_records)
            logger.success(
                f"✅ Backfilled HV voor {sym}: {new_records[0]['date']} → {new_records[-1]['date']} ({len(new_records)} records toegevoegd)"
            )
        else:
            logger.info(f"⏭️ {sym}: geen nieuwe HV-records")
