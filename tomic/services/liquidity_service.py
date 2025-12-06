"""Liquidity metrics service for calculating ATM volume and open interest.

Uses ORATS cached data to calculate average liquidity metrics for symbols.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tomic.config import get as cfg_get
from tomic.logutils import logger


@dataclass
class LiquidityMetrics:
    """Liquidity metrics for a symbol."""

    symbol: str
    avg_atm_call_volume: Optional[int] = None
    avg_atm_call_oi: Optional[int] = None
    avg_atm_put_volume: Optional[int] = None
    avg_atm_put_oi: Optional[int] = None
    days_analyzed: int = 0
    data_start: Optional[date] = None
    data_end: Optional[date] = None

    @property
    def total_avg_volume(self) -> Optional[int]:
        """Total average ATM volume (calls + puts)."""
        if self.avg_atm_call_volume is None and self.avg_atm_put_volume is None:
            return None
        call_vol = self.avg_atm_call_volume or 0
        put_vol = self.avg_atm_put_volume or 0
        return call_vol + put_vol

    @property
    def total_avg_oi(self) -> Optional[int]:
        """Total average ATM open interest (calls + puts)."""
        if self.avg_atm_call_oi is None and self.avg_atm_put_oi is None:
            return None
        call_oi = self.avg_atm_call_oi or 0
        put_oi = self.avg_atm_put_oi or 0
        return call_oi + put_oi

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "symbol": self.symbol,
            "avg_atm_call_volume": self.avg_atm_call_volume,
            "avg_atm_call_oi": self.avg_atm_call_oi,
            "avg_atm_put_volume": self.avg_atm_put_volume,
            "avg_atm_put_oi": self.avg_atm_put_oi,
            "days_analyzed": self.days_analyzed,
            "data_start": str(self.data_start) if self.data_start else None,
            "data_end": str(self.data_end) if self.data_end else None,
        }


class LiquidityService:
    """Service for calculating liquidity metrics from ORATS data."""

    def __init__(self, cache_dir: Optional[Path] = None):
        """Initialize the liquidity service.

        Args:
            cache_dir: Directory containing ORATS ZIP files.
                      Defaults to ORATS_CACHE_DIR from config.
        """
        if cache_dir is None:
            base_dir = Path(__file__).resolve().parent.parent.parent
            cache_dir = base_dir / cfg_get("ORATS_CACHE_DIR", "tomic/data/orats_cache")
        self.cache_dir = cache_dir.expanduser()

    def _get_available_dates(self, lookback_days: int = 30) -> List[date]:
        """Get available trading dates from ORATS cache.

        Args:
            lookback_days: Number of days to look back.

        Returns:
            List of available dates, sorted descending (newest first).
        """
        available = []
        end_date = date.today()
        start_date = end_date - timedelta(days=lookback_days + 10)  # Buffer for weekends

        # Scan cache directories for available files
        for year_dir in self.cache_dir.iterdir():
            if not year_dir.is_dir() or not year_dir.name.isdigit():
                continue

            for zip_file in year_dir.glob("ORATS_SMV_Strikes_*.zip"):
                try:
                    date_str = zip_file.stem.split("_")[-1]
                    file_date = date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))
                    if start_date <= file_date <= end_date:
                        available.append(file_date)
                except (ValueError, IndexError):
                    continue

        return sorted(available, reverse=True)[:lookback_days]

    def calculate_liquidity(
        self,
        symbol: str,
        lookback_days: int = 30,
        target_dte_range: Tuple[int, int] = (20, 60),
    ) -> LiquidityMetrics:
        """Calculate average liquidity metrics for a symbol.

        Uses ORATS data to find ATM options and calculate average volume/OI.

        Args:
            symbol: Stock symbol.
            lookback_days: Number of trading days to analyze.
            target_dte_range: DTE range for ATM options (min, max).

        Returns:
            LiquidityMetrics with calculated averages.
        """
        # Import here to avoid circular imports
        from tomic.backtest.option_chain_loader import OptionChainLoader

        symbol = symbol.upper()
        metrics = LiquidityMetrics(symbol=symbol)

        loader = OptionChainLoader(self.cache_dir)
        available_dates = self._get_available_dates(lookback_days)

        if not available_dates:
            logger.warning(f"No ORATS data available for liquidity calculation")
            return metrics

        call_volumes: List[int] = []
        call_ois: List[int] = []
        put_volumes: List[int] = []
        put_ois: List[int] = []
        analyzed_dates: List[date] = []

        for trade_date in available_dates:
            try:
                chain = loader.load_chain(symbol, trade_date)
                if chain is None or not chain.options:
                    continue

                # Find ATM options in target DTE range
                atm_calls, atm_puts = self._find_atm_options(
                    chain, target_dte_range
                )

                if atm_calls:
                    for opt in atm_calls:
                        if opt.volume is not None:
                            call_volumes.append(opt.volume)
                        if opt.open_interest is not None:
                            call_ois.append(opt.open_interest)

                if atm_puts:
                    for opt in atm_puts:
                        if opt.volume is not None:
                            put_volumes.append(opt.volume)
                        if opt.open_interest is not None:
                            put_ois.append(opt.open_interest)

                analyzed_dates.append(trade_date)

            except Exception as e:
                logger.debug(f"Error loading chain for {symbol} on {trade_date}: {e}")
                continue

        # Calculate averages
        if call_volumes:
            metrics.avg_atm_call_volume = int(sum(call_volumes) / len(call_volumes))
        if call_ois:
            metrics.avg_atm_call_oi = int(sum(call_ois) / len(call_ois))
        if put_volumes:
            metrics.avg_atm_put_volume = int(sum(put_volumes) / len(put_volumes))
        if put_ois:
            metrics.avg_atm_put_oi = int(sum(put_ois) / len(put_ois))

        metrics.days_analyzed = len(analyzed_dates)
        if analyzed_dates:
            metrics.data_start = min(analyzed_dates)
            metrics.data_end = max(analyzed_dates)

        return metrics

    def _find_atm_options(
        self,
        chain,
        dte_range: Tuple[int, int],
    ) -> Tuple[List, List]:
        """Find ATM call and put options within DTE range.

        Args:
            chain: OptionChain object.
            dte_range: (min_dte, max_dte) range.

        Returns:
            Tuple of (atm_calls, atm_puts).
        """
        min_dte, max_dte = dte_range
        spot = chain.spot_price

        if spot is None or spot <= 0:
            return [], []

        # Filter options by DTE
        options_in_range = chain.filter_by_dte_range(min_dte, max_dte)

        if not options_in_range:
            return [], []

        # Find options closest to ATM (within 2% of spot)
        atm_tolerance = spot * 0.02

        atm_calls = [
            opt for opt in options_in_range
            if opt.option_type == "C" and abs(opt.strike - spot) <= atm_tolerance
        ]

        atm_puts = [
            opt for opt in options_in_range
            if opt.option_type == "P" and abs(opt.strike - spot) <= atm_tolerance
        ]

        return atm_calls, atm_puts

    def calculate_liquidity_batch(
        self,
        symbols: List[str],
        lookback_days: int = 30,
    ) -> Dict[str, LiquidityMetrics]:
        """Calculate liquidity metrics for multiple symbols.

        Args:
            symbols: List of stock symbols.
            lookback_days: Number of trading days to analyze.

        Returns:
            Dictionary mapping symbol to LiquidityMetrics.
        """
        results = {}
        for symbol in symbols:
            logger.info(f"Calculating liquidity for {symbol}...")
            results[symbol.upper()] = self.calculate_liquidity(
                symbol, lookback_days
            )
        return results


# Module-level instance for convenience
_service: Optional[LiquidityService] = None


def get_liquidity_service() -> LiquidityService:
    """Get or create the liquidity service singleton."""
    global _service
    if _service is None:
        _service = LiquidityService()
    return _service
