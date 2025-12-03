"""Data loader for historical IV data.

Loads and normalizes historical IV data from various sources:
- ORATS historical data (2007+)
- Existing IV daily summary files
- Price history for spot prices
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tomic.backtest.config import BacktestConfig
from tomic.backtest.results import IVDataPoint
from tomic.config import get as cfg_get
from tomic.logutils import logger


@dataclass
class SpotOHLC:
    """Spot price data with OHLC for gap-risk simulation."""

    date: date
    open: float
    high: float
    low: float
    close: float

    @property
    def overnight_gap_pct(self) -> float:
        """Calculate overnight gap as percentage from previous close to open.

        Note: Requires previous day's close to be set externally.
        This property returns 0 - use calculate_gap() with previous close.
        """
        return 0.0

    def calculate_gap(self, prev_close: float) -> float:
        """Calculate overnight gap percentage from previous close.

        Args:
            prev_close: Previous day's closing price

        Returns:
            Gap as percentage (e.g., -5.0 for a 5% gap down)
        """
        if prev_close <= 0:
            return 0.0
        return ((self.open - prev_close) / prev_close) * 100

    def intraday_range_pct(self) -> float:
        """Calculate intraday range as percentage of open."""
        if self.open <= 0:
            return 0.0
        return ((self.high - self.low) / self.open) * 100


class IVTimeSeries:
    """Time series of IV data for a single symbol."""

    def __init__(self, symbol: str, data_points: List[IVDataPoint] = None):
        self.symbol = symbol
        self._data: Dict[date, IVDataPoint] = {}

        if data_points:
            for dp in data_points:
                if dp.date is not None:
                    self._data[dp.date] = dp

    def add(self, data_point: IVDataPoint) -> None:
        """Add a data point to the time series."""
        if data_point.date is not None:
            self._data[data_point.date] = data_point

    def get(self, dt: date) -> Optional[IVDataPoint]:
        """Get data point for a specific date."""
        return self._data.get(dt)

    def get_range(self, start: date, end: date) -> List[IVDataPoint]:
        """Get all data points within a date range (inclusive)."""
        result = []
        for dt, dp in sorted(self._data.items()):
            if start <= dt <= end:
                result.append(dp)
        return result

    def dates(self) -> List[date]:
        """Get all dates in the time series, sorted."""
        return sorted(self._data.keys())

    def __len__(self) -> int:
        return len(self._data)

    def __iter__(self):
        """Iterate over data points in date order."""
        for dt in sorted(self._data.keys()):
            yield self._data[dt]

    @property
    def start_date(self) -> Optional[date]:
        """Earliest date in the series."""
        dates = self.dates()
        return dates[0] if dates else None

    @property
    def end_date(self) -> Optional[date]:
        """Latest date in the series."""
        dates = self.dates()
        return dates[-1] if dates else None


class DataLoader:
    """Loads and manages historical IV data for backtesting."""

    def __init__(self, config: BacktestConfig):
        self.config = config
        self._iv_data: Dict[str, IVTimeSeries] = {}
        self._price_data: Dict[str, Dict[date, float]] = {}

    def load_all(self) -> Dict[str, IVTimeSeries]:
        """Load IV data for all configured symbols.

        Returns:
            Dictionary mapping symbol to IVTimeSeries.
        """
        for symbol in self.config.symbols:
            try:
                ts = self._load_symbol_iv(symbol)
                if ts and len(ts) > 0:
                    self._iv_data[symbol] = ts
                    logger.info(
                        f"Loaded {len(ts)} IV data points for {symbol} "
                        f"({ts.start_date} to {ts.end_date})"
                    )
                else:
                    logger.warning(f"No IV data found for {symbol}")
            except Exception as e:
                logger.error(f"Error loading IV data for {symbol}: {e}")

        return self._iv_data

    def _load_symbol_iv(self, symbol: str) -> Optional[IVTimeSeries]:
        """Load IV data for a single symbol from available sources."""
        # Try ORATS historical data first (if available)
        orats_data = self._load_orats_historical(symbol)
        if orats_data and len(orats_data) > 0:
            return orats_data

        # Fall back to IV daily summary
        return self._load_iv_daily_summary(symbol)

    def _load_orats_historical(self, symbol: str) -> Optional[IVTimeSeries]:
        """Load historical IV from ORATS data files.

        Expected file location: tomic/data/orats_historical/{symbol}.json
        Expected format: List of records with fields:
            - trade_date: "YYYY-MM-DD"
            - iv30: ATM 30-day IV
            - iv_rank: IV rank (0-100)
            - iv_percentile: IV percentile (0-100)
            - hv30: 30-day historical volatility
            - skew: Put/call skew
            - contango: Term structure
        """
        base_dir = Path(__file__).resolve().parent.parent.parent
        orats_path = base_dir / "tomic" / "data" / "orats_historical" / f"{symbol}.json"

        if not orats_path.exists():
            return None

        try:
            with open(orats_path, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
        except Exception as e:
            logger.debug(f"Could not load ORATS data for {symbol}: {e}")
            return None

        if not isinstance(raw_data, list):
            return None

        ts = IVTimeSeries(symbol)
        start = date.fromisoformat(self.config.start_date)
        end = date.fromisoformat(self.config.end_date)

        for record in raw_data:
            try:
                date_str = record.get("trade_date") or record.get("date")
                if not date_str:
                    continue

                dt = date.fromisoformat(date_str)
                if dt < start or dt > end:
                    continue

                # Map ORATS fields to our standard format
                dp = IVDataPoint(
                    date=dt,
                    symbol=symbol,
                    atm_iv=self._parse_float(record.get("iv30") or record.get("atm_iv")),
                    iv_rank=self._parse_float(record.get("iv_rank")),
                    iv_percentile=self._parse_float(record.get("iv_percentile")),
                    hv30=self._parse_float(record.get("hv30")),
                    skew=self._parse_float(record.get("skew")),
                    term_m1_m2=self._parse_float(record.get("contango") or record.get("term_m1_m2")),
                    term_m1_m3=self._parse_float(record.get("term_m1_m3")),
                    spot_price=self._parse_float(record.get("close") or record.get("spot_price")),
                )

                if dp.is_valid():
                    ts.add(dp)

            except (ValueError, KeyError) as e:
                logger.debug(f"Skipping invalid ORATS record for {symbol}: {e}")
                continue

        return ts if len(ts) > 0 else None

    def _load_iv_daily_summary(self, symbol: str) -> Optional[IVTimeSeries]:
        """Load IV data from existing IV daily summary files.

        For older data that lacks iv_percentile, we calculate it using a
        rolling 252-day (1 year) window of ATM IV values.
        """
        iv_dir = cfg_get("IV_DAILY_SUMMARY_DIR", "tomic/data/iv_daily_summary")
        base_dir = Path(__file__).resolve().parent.parent.parent
        iv_path = base_dir / iv_dir / f"{symbol}.json"

        if not iv_path.exists():
            return None

        try:
            with open(iv_path, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
        except Exception as e:
            logger.debug(f"Could not load IV summary for {symbol}: {e}")
            return None

        if not isinstance(raw_data, list):
            return None

        # First pass: collect all data points with their ATM IV values
        # to calculate iv_percentile for records that don't have it
        all_data_points: List[Tuple[date, IVDataPoint, Dict]] = []
        iv_history: List[Tuple[date, float]] = []  # For percentile calculation

        for record in raw_data:
            dp = IVDataPoint.from_dict(record, symbol)
            if dp.date and dp.atm_iv is not None:
                all_data_points.append((dp.date, dp, record))
                iv_history.append((dp.date, dp.atm_iv))

        # Sort by date
        all_data_points.sort(key=lambda x: x[0])
        iv_history.sort(key=lambda x: x[0])

        # Second pass: calculate iv_percentile for records that don't have it
        # using a 252-day lookback window
        LOOKBACK_DAYS = 252
        ts = IVTimeSeries(symbol)
        start = date.fromisoformat(self.config.start_date)
        end = date.fromisoformat(self.config.end_date)

        for i, (dt, dp, record) in enumerate(all_data_points):
            if dt < start or dt > end:
                continue

            # If iv_percentile is missing, calculate it
            if dp.iv_percentile is None and dp.atm_iv is not None:
                # Find IV values in the lookback window
                lookback_ivs = [
                    iv for d, iv in iv_history[:i+1]
                    if (dt - d).days <= LOOKBACK_DAYS and (dt - d).days >= 0
                ]

                if len(lookback_ivs) >= 20:  # Need at least 20 data points
                    # Calculate percentile: what % of historical values is current IV above?
                    current_iv = dp.atm_iv
                    below_count = sum(1 for iv in lookback_ivs if iv < current_iv)
                    dp.iv_percentile = (below_count / len(lookback_ivs)) * 100

                    # Also calculate iv_rank if missing
                    if dp.iv_rank is None:
                        min_iv = min(lookback_ivs)
                        max_iv = max(lookback_ivs)
                        if max_iv > min_iv:
                            dp.iv_rank = ((current_iv - min_iv) / (max_iv - min_iv)) * 100

            if dp.is_valid():
                ts.add(dp)

        return ts if len(ts) > 0 else None

    def load_spot_prices(self, symbol: str) -> Dict[date, float]:
        """Load historical spot prices for a symbol.

        Returns:
            Dictionary mapping date to close price.
        """
        if symbol in self._price_data:
            return self._price_data[symbol]

        price_dir = cfg_get("PRICE_HISTORY_DIR", "tomic/data/spot_prices")
        base_dir = Path(__file__).resolve().parent.parent.parent
        price_path = base_dir / price_dir / f"{symbol}.json"

        prices: Dict[date, float] = {}

        if price_path.exists():
            try:
                with open(price_path, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)

                if isinstance(raw_data, list):
                    for record in raw_data:
                        try:
                            dt = date.fromisoformat(record.get("date", ""))
                            close = float(record.get("close", 0))
                            if close > 0:
                                prices[dt] = close
                        except (ValueError, TypeError):
                            continue

            except Exception as e:
                logger.debug(f"Could not load price history for {symbol}: {e}")

        self._price_data[symbol] = prices
        return prices

    def load_spot_ohlc(self, symbol: str) -> Dict[date, SpotOHLC]:
        """Load historical OHLC data for gap-risk simulation.

        Returns:
            Dictionary mapping date to SpotOHLC with full OHLC data.
        """
        price_dir = cfg_get("PRICE_HISTORY_DIR", "tomic/data/spot_prices")
        base_dir = Path(__file__).resolve().parent.parent.parent
        price_path = base_dir / price_dir / f"{symbol}.json"

        ohlc_data: Dict[date, SpotOHLC] = {}

        if price_path.exists():
            try:
                with open(price_path, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)

                if isinstance(raw_data, list):
                    for record in raw_data:
                        try:
                            dt = date.fromisoformat(record.get("date", ""))
                            close = float(record.get("close", 0))
                            # Use close as fallback for missing OHLC
                            open_price = float(record.get("open", close) or close)
                            high = float(record.get("high", close) or close)
                            low = float(record.get("low", close) or close)

                            if close > 0:
                                ohlc_data[dt] = SpotOHLC(
                                    date=dt,
                                    open=open_price,
                                    high=high,
                                    low=low,
                                    close=close,
                                )
                        except (ValueError, TypeError):
                            continue

            except Exception as e:
                logger.debug(f"Could not load OHLC history for {symbol}: {e}")

        return ohlc_data

    def get_iv_data(self, symbol: str) -> Optional[IVTimeSeries]:
        """Get loaded IV data for a symbol."""
        return self._iv_data.get(symbol)

    def get_all_trading_dates(self) -> List[date]:
        """Get union of all trading dates across all symbols, sorted."""
        all_dates = set()
        for ts in self._iv_data.values():
            all_dates.update(ts.dates())
        return sorted(all_dates)

    def split_by_date(
        self, split_date: date
    ) -> Tuple[Dict[str, IVTimeSeries], Dict[str, IVTimeSeries]]:
        """Split all data into before/after a given date.

        Args:
            split_date: Date to split on (inclusive in first set)

        Returns:
            Tuple of (in_sample_data, out_sample_data)
        """
        in_sample: Dict[str, IVTimeSeries] = {}
        out_sample: Dict[str, IVTimeSeries] = {}

        for symbol, ts in self._iv_data.items():
            in_sample_points = []
            out_sample_points = []

            for dp in ts:
                if dp.date <= split_date:
                    in_sample_points.append(dp)
                else:
                    out_sample_points.append(dp)

            if in_sample_points:
                in_sample[symbol] = IVTimeSeries(symbol, in_sample_points)
            if out_sample_points:
                out_sample[symbol] = IVTimeSeries(symbol, out_sample_points)

        return in_sample, out_sample

    def split_by_ratio(
        self, in_sample_ratio: float
    ) -> Tuple[Dict[str, IVTimeSeries], Dict[str, IVTimeSeries], Dict[str, date]]:
        """Split data per symbol based on ratio of actual available data.

        Each symbol is split independently based on its own date range,
        ensuring both in-sample and out-of-sample periods have data.

        Args:
            in_sample_ratio: Ratio of data to use for in-sample (e.g., 0.3 for 30%)

        Returns:
            Tuple of (in_sample_data, out_sample_data, split_dates_per_symbol)
        """
        from datetime import timedelta

        in_sample: Dict[str, IVTimeSeries] = {}
        out_sample: Dict[str, IVTimeSeries] = {}
        split_dates: Dict[str, date] = {}

        for symbol, ts in self._iv_data.items():
            if len(ts) == 0:
                continue

            # Get actual date range for this symbol
            symbol_start = ts.start_date
            symbol_end = ts.end_date

            if symbol_start is None or symbol_end is None:
                continue

            # Calculate split date based on actual data range
            total_days = (symbol_end - symbol_start).days
            in_sample_days = int(total_days * in_sample_ratio)
            symbol_split_date = symbol_start + timedelta(days=in_sample_days)

            split_dates[symbol] = symbol_split_date

            # Split the data
            in_sample_points = []
            out_sample_points = []

            for dp in ts:
                if dp.date <= symbol_split_date:
                    in_sample_points.append(dp)
                else:
                    out_sample_points.append(dp)

            if in_sample_points:
                in_sample[symbol] = IVTimeSeries(symbol, in_sample_points)
            if out_sample_points:
                out_sample[symbol] = IVTimeSeries(symbol, out_sample_points)

            logger.info(
                f"  {symbol}: split at {symbol_split_date} "
                f"(data: {symbol_start} to {symbol_end}, "
                f"in-sample={len(in_sample_points)}, out-of-sample={len(out_sample_points)})"
            )

        return in_sample, out_sample, split_dates

    @staticmethod
    def _parse_float(value: Any) -> Optional[float]:
        """Safely parse a value to float."""
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    def get_data_summary(self) -> Dict[str, Any]:
        """Get summary of loaded data."""
        summary = {
            "symbols_loaded": len(self._iv_data),
            "total_data_points": sum(len(ts) for ts in self._iv_data.values()),
            "per_symbol": {},
        }

        for symbol, ts in self._iv_data.items():
            summary["per_symbol"][symbol] = {
                "data_points": len(ts),
                "start_date": str(ts.start_date) if ts.start_date else None,
                "end_date": str(ts.end_date) if ts.end_date else None,
            }

        return summary


__all__ = ["DataLoader", "IVTimeSeries", "SpotOHLC"]
