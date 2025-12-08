"""Correlation service for calculating price correlations between symbols.

Uses spot price data to calculate Pearson correlation coefficients.
Helps identify diversification opportunities by finding low-correlation symbols.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from tomic.logutils import logger


@dataclass
class CorrelationResult:
    """Result of correlation calculation between two symbols."""

    symbol1: str
    symbol2: str
    correlation: float
    days_overlap: int
    data_start: Optional[str] = None
    data_end: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "symbol1": self.symbol1,
            "symbol2": self.symbol2,
            "correlation": round(self.correlation, 3),
            "days_overlap": self.days_overlap,
            "data_start": self.data_start,
            "data_end": self.data_end,
        }


class CorrelationService:
    """Service for calculating price correlations from spot price data."""

    def __init__(self, data_dir: Optional[Path] = None):
        """Initialize the correlation service.

        Args:
            data_dir: Directory containing spot price JSON files.
                      Defaults to tomic/data/spot_prices.
        """
        if data_dir is None:
            base_dir = Path(__file__).resolve().parent.parent.parent
            data_dir = base_dir / "tomic" / "data" / "spot_prices"
        self.data_dir = data_dir
        self._price_cache: Dict[str, Dict[str, float]] = {}

    def _load_spot_prices(self, symbol: str) -> Dict[str, float]:
        """Load spot prices for a symbol from JSON file.

        Args:
            symbol: Stock symbol.

        Returns:
            Dictionary mapping date string to closing price.
        """
        symbol = symbol.upper()

        if symbol in self._price_cache:
            return self._price_cache[symbol]

        # Try both naming conventions
        candidates = [
            self.data_dir / f"{symbol}.json",
            self.data_dir / f"{symbol}_spot.json",
        ]

        for path in candidates:
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    # Handle different JSON formats
                    prices = {}
                    if isinstance(data, list):
                        # Format: [{"date": "2024-01-01", "close": 150.0}, ...]
                        for item in data:
                            date_str = item.get("date") or item.get("t")
                            close = item.get("close") or item.get("c")
                            if date_str and close is not None:
                                # Normalize date format
                                if isinstance(date_str, str) and len(date_str) >= 10:
                                    prices[date_str[:10]] = float(close)
                    elif isinstance(data, dict):
                        # Format: {"2024-01-01": 150.0, ...} or {"prices": [...]}
                        if "prices" in data:
                            for item in data["prices"]:
                                date_str = item.get("date") or item.get("t")
                                close = item.get("close") or item.get("c")
                                if date_str and close is not None:
                                    prices[date_str[:10]] = float(close)
                        else:
                            for date_str, price in data.items():
                                if isinstance(price, (int, float)):
                                    prices[date_str[:10]] = float(price)

                    self._price_cache[symbol] = prices
                    return prices

                except (json.JSONDecodeError, OSError) as e:
                    logger.warning(f"Failed to load spot prices for {symbol}: {e}")

        return {}

    def calculate_correlation(
        self,
        symbol1: str,
        symbol2: str,
        lookback_days: int = 60,
    ) -> Optional[CorrelationResult]:
        """Calculate Pearson correlation between two symbols.

        Uses daily returns (percentage change) for correlation calculation.

        Args:
            symbol1: First symbol.
            symbol2: Second symbol.
            lookback_days: Number of days to look back.

        Returns:
            CorrelationResult or None if insufficient data.
        """
        prices1 = self._load_spot_prices(symbol1)
        prices2 = self._load_spot_prices(symbol2)

        if not prices1 or not prices2:
            return None

        # Find overlapping dates
        common_dates = sorted(set(prices1.keys()) & set(prices2.keys()))

        # Filter to lookback period
        cutoff = (datetime.now() - timedelta(days=lookback_days + 30)).strftime("%Y-%m-%d")
        common_dates = [d for d in common_dates if d >= cutoff]

        if len(common_dates) < 20:  # Need at least 20 data points
            return None

        # Take most recent lookback_days
        common_dates = common_dates[-lookback_days:]

        # Calculate daily returns
        returns1 = []
        returns2 = []

        for i in range(1, len(common_dates)):
            prev_date = common_dates[i - 1]
            curr_date = common_dates[i]

            p1_prev = prices1[prev_date]
            p1_curr = prices1[curr_date]
            p2_prev = prices2[prev_date]
            p2_curr = prices2[curr_date]

            if p1_prev > 0 and p2_prev > 0:
                ret1 = (p1_curr - p1_prev) / p1_prev
                ret2 = (p2_curr - p2_prev) / p2_prev
                returns1.append(ret1)
                returns2.append(ret2)

        if len(returns1) < 15:
            return None

        # Calculate Pearson correlation
        arr1 = np.array(returns1)
        arr2 = np.array(returns2)

        correlation = np.corrcoef(arr1, arr2)[0, 1]

        if np.isnan(correlation):
            return None

        return CorrelationResult(
            symbol1=symbol1.upper(),
            symbol2=symbol2.upper(),
            correlation=float(correlation),
            days_overlap=len(returns1),
            data_start=common_dates[0],
            data_end=common_dates[-1],
        )

    def calculate_basket_correlation(
        self,
        candidate_symbol: str,
        basket_symbols: List[str],
        lookback_days: int = 60,
    ) -> Optional[float]:
        """Calculate average correlation of a candidate with basket symbols.

        Args:
            candidate_symbol: Symbol to evaluate.
            basket_symbols: List of symbols in the current basket.
            lookback_days: Number of days to look back.

        Returns:
            Average correlation with basket, or None if insufficient data.
        """
        if not basket_symbols:
            return 0.0  # No basket = no correlation

        correlations = []
        for basket_symbol in basket_symbols:
            if basket_symbol.upper() == candidate_symbol.upper():
                continue

            result = self.calculate_correlation(
                candidate_symbol,
                basket_symbol,
                lookback_days=lookback_days,
            )

            if result is not None:
                correlations.append(result.correlation)

        if not correlations:
            return None

        return sum(correlations) / len(correlations)

    def get_correlation_matrix(
        self,
        symbols: List[str],
        lookback_days: int = 60,
    ) -> Dict[str, Dict[str, float]]:
        """Calculate full correlation matrix for a list of symbols.

        Args:
            symbols: List of symbols.
            lookback_days: Number of days to look back.

        Returns:
            Nested dictionary with correlations: matrix[sym1][sym2] = correlation.
        """
        matrix: Dict[str, Dict[str, float]] = defaultdict(dict)

        for i, sym1 in enumerate(symbols):
            matrix[sym1][sym1] = 1.0
            for sym2 in symbols[i + 1:]:
                result = self.calculate_correlation(sym1, sym2, lookback_days)
                if result:
                    matrix[sym1][sym2] = result.correlation
                    matrix[sym2][sym1] = result.correlation

        return dict(matrix)

    def clear_cache(self) -> None:
        """Clear the price cache."""
        self._price_cache.clear()


# Module-level instance
_service: Optional[CorrelationService] = None


def get_correlation_service() -> CorrelationService:
    """Get or create the correlation service singleton."""
    global _service
    if _service is None:
        _service = CorrelationService()
    return _service
