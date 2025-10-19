from __future__ import annotations

"""Services for computing historical volatility backfills."""

from dataclasses import dataclass
from datetime import date
from typing import Sequence

from ...analysis.metrics import historical_volatility
from ...config import get as cfg_get
from ...logutils import logger
from ...utils import load_price_history, today
from .storage_service import HistoricalVolatilityStorageService

DEFAULT_WINDOWS: tuple[int, ...] = (20, 30, 90, 252)


@dataclass
class HistoricalVolatilityResult:
    symbol: str
    records: list[dict]


class HistoricalVolatilityCalculatorService:
    """Calculate historical volatility timeseries for symbols."""

    def __init__(self, windows: Sequence[int] | None = None) -> None:
        self.windows = tuple(sorted(set(int(w) for w in (windows or DEFAULT_WINDOWS))))
        if not self.windows:
            raise ValueError("At least one window is required")
        self.max_window = max(self.windows)

    def load_price_data(self, symbol: str) -> list[tuple[str, float]]:
        """Return ordered (date, close) data for ``symbol``."""

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
        records.sort(key=lambda item: item[0])
        return records

    def compute_new_records(
        self,
        symbol: str,
        price_records: Sequence[tuple[str, float]],
        existing_dates: set[str],
        *,
        end_date: date,
    ) -> list[dict]:
        """Return new HV records constrained by ``existing_dates`` and ``end_date``."""

        if not price_records:
            return []
        dates, closes = zip(*price_records)
        end_str = end_date.strftime("%Y-%m-%d")
        new_records: list[dict] = []
        for idx in range(self.max_window, len(dates)):
            date_str = dates[idx]
            if date_str > end_str:
                break
            if date_str in existing_dates:
                continue
            record: dict[str, float | str] = {"date": date_str}
            for window in self.windows:
                hv_value = historical_volatility(closes[: idx + 1], window=window)
                if hv_value is not None:
                    record[f"hv{window}"] = round(hv_value / 100, 9)
            if record.get(f"hv{self.max_window}") is None:
                logger.warning(
                    "⚠️ %s: insufficient spot data for hv%d on %s",
                    symbol,
                    self.max_window,
                    date_str,
                )
                continue
            new_records.append(record)
        return new_records


class HistoricalVolatilityBackfillService:
    """Orchestrates loading, computing and storing HV data."""

    def __init__(
        self,
        *,
        storage: HistoricalVolatilityStorageService | None = None,
        calculator: HistoricalVolatilityCalculatorService | None = None,
    ) -> None:
        self.storage = storage or HistoricalVolatilityStorageService()
        self.calculator = calculator or HistoricalVolatilityCalculatorService()

    def resolve_symbols(self, symbols: Sequence[str] | None) -> list[str]:
        if symbols:
            return [s.upper() for s in symbols]
        configured = cfg_get("DEFAULT_SYMBOLS", []) or []
        return [str(symbol).upper() for symbol in configured]

    def run(self, symbols: Sequence[str] | None = None) -> list[HistoricalVolatilityResult]:
        """Run the backfill workflow for ``symbols`` and return results."""

        logger.info("🚀 Backfilling historical volatility")
        resolved = self.resolve_symbols(symbols)
        results: list[HistoricalVolatilityResult] = []
        end_date = today()
        for symbol in resolved:
            price_records = self.calculator.load_price_data(symbol)
            if not price_records:
                logger.warning("⚠️ Geen prijsdata voor %s", symbol)
                continue
            dates = [record[0] for record in price_records]
            if len(dates) != len(set(dates)):
                logger.error("❌ %s: dubbele datums in spotprijsdata", symbol)
                continue
            if len(dates) <= self.calculator.max_window:
                logger.warning(
                    "⚠️ %s: te weinig spotdata (<%d dagen)",
                    symbol,
                    self.calculator.max_window,
                )
                continue
            existing, _ = self.storage.load(symbol)
            existing_dates = {rec.get("date") for rec in existing if isinstance(rec, dict)}
            new_records = self.calculator.compute_new_records(
                symbol,
                price_records,
                existing_dates,
                end_date=end_date,
            )
            if new_records:
                self.storage.append(symbol, new_records)
                start = new_records[0]["date"]
                end = new_records[-1]["date"]
                count = len(new_records)
                logger.success(
                    f"✅ Backfilled HV voor {symbol}: {start} → {end} ({count} records toegevoegd)"
                )
                results.append(HistoricalVolatilityResult(symbol=symbol, records=new_records))
            else:
                logger.info("⏭️ %s: geen nieuwe HV-records", symbol)
        return results


__all__ = [
    "HistoricalVolatilityBackfillService",
    "HistoricalVolatilityCalculatorService",
    "HistoricalVolatilityResult",
]
