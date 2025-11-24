"""Entry signal generator for backtesting.

Detects entry signals based on IV metrics and configured entry rules.
The core hypothesis is that elevated IV (relative to HV) provides
favorable entry conditions for premium selling strategies.
"""

from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

from tomic.backtest.config import BacktestConfig, EntryRulesConfig
from tomic.backtest.data_loader import IVTimeSeries
from tomic.backtest.results import EntrySignal, IVDataPoint
from tomic.logutils import logger


class SignalGenerator:
    """Generates entry signals based on IV metrics.

    Entry signals are generated when IV metrics meet configured thresholds.
    The primary signal is IV percentile, with optional filters for:
    - IV rank
    - Skew
    - Term structure
    - IV-HV spread
    """

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.entry_rules = config.entry_rules

    def scan_for_signals(
        self,
        iv_data: Dict[str, IVTimeSeries],
        trading_date: date,
        open_positions: Dict[str, bool],
    ) -> List[EntrySignal]:
        """Scan all symbols for entry signals on a given date.

        Args:
            iv_data: Dictionary of symbol -> IVTimeSeries
            trading_date: Date to check for signals
            open_positions: Dict of symbol -> True if position is open

        Returns:
            List of EntrySignal objects for symbols meeting criteria.
        """
        signals = []

        for symbol, ts in iv_data.items():
            # Skip if we already have a position in this symbol
            if open_positions.get(symbol, False):
                continue

            # Get IV data for this date
            data_point = ts.get(trading_date)
            if data_point is None or not data_point.is_valid():
                continue

            # Check if entry criteria are met
            signal = self._evaluate_entry(data_point)
            if signal is not None:
                signals.append(signal)

        return signals

    def _evaluate_entry(self, dp: IVDataPoint) -> Optional[EntrySignal]:
        """Evaluate if a data point meets entry criteria.

        Args:
            dp: IVDataPoint to evaluate

        Returns:
            EntrySignal if criteria are met, None otherwise.
        """
        rules = self.entry_rules

        # Primary check: IV percentile minimum
        if dp.iv_percentile is None:
            return None

        if dp.iv_percentile < rules.iv_percentile_min:
            return None

        # Optional: IV rank minimum
        if rules.iv_rank_min is not None:
            if dp.iv_rank is None or dp.iv_rank < rules.iv_rank_min:
                return None

        # Optional: Skew range
        if rules.skew_min is not None and dp.skew is not None:
            if dp.skew < rules.skew_min:
                return None
        if rules.skew_max is not None and dp.skew is not None:
            if dp.skew > rules.skew_max:
                return None

        # Optional: Term structure range
        term = dp.term_m1_m2  # Use M1-M2 term structure
        if rules.term_structure_min is not None and term is not None:
            if term < rules.term_structure_min:
                return None
        if rules.term_structure_max is not None and term is not None:
            if term > rules.term_structure_max:
                return None

        # Optional: IV-HV spread minimum
        if rules.iv_hv_spread_min is not None:
            if dp.atm_iv is not None and dp.hv30 is not None:
                iv_hv_spread = dp.atm_iv - dp.hv30
                if iv_hv_spread < rules.iv_hv_spread_min:
                    return None

        # All criteria met - calculate signal strength
        signal_strength = self._calculate_signal_strength(dp)

        return EntrySignal(
            date=dp.date,
            symbol=dp.symbol,
            iv_at_entry=dp.atm_iv,
            iv_rank_at_entry=dp.iv_rank,
            iv_percentile_at_entry=dp.iv_percentile,
            hv_at_entry=dp.hv30,
            skew_at_entry=dp.skew,
            term_at_entry=dp.term_m1_m2,
            spot_at_entry=dp.spot_price,
            signal_strength=signal_strength,
        )

    def _calculate_signal_strength(self, dp: IVDataPoint) -> float:
        """Calculate composite signal strength score (0-100).

        Higher scores indicate stronger entry signals based on:
        - IV percentile (primary factor)
        - IV-HV spread
        - IV rank
        """
        score = 0.0
        weights_used = 0.0

        # IV percentile contribution (0-50 points)
        if dp.iv_percentile is not None:
            # Scale: 60% = 0 points, 100% = 50 points
            pct_score = max(0, (dp.iv_percentile - 60) / 40) * 50
            score += pct_score
            weights_used += 50

        # IV-HV spread contribution (0-25 points)
        if dp.atm_iv is not None and dp.hv30 is not None:
            spread = dp.atm_iv - dp.hv30
            # Scale: 0 spread = 0 points, 0.10+ spread = 25 points
            spread_score = min(25, max(0, spread / 0.10) * 25)
            score += spread_score
            weights_used += 25

        # IV rank contribution (0-25 points)
        if dp.iv_rank is not None:
            # Scale: 0% = 0 points, 100% = 25 points
            # Note: iv_rank in data is typically 0-100, not 0-1
            rank_normalized = dp.iv_rank / 100 if dp.iv_rank > 1 else dp.iv_rank
            rank_score = rank_normalized * 25
            score += rank_score
            weights_used += 25

        # Normalize to 0-100 scale
        if weights_used > 0:
            score = (score / weights_used) * 100

        return round(score, 2)

    def get_signal_summary(
        self, signals: List[EntrySignal]
    ) -> Dict[str, int]:
        """Get summary of signals by symbol."""
        summary: Dict[str, int] = {}
        for signal in signals:
            summary[signal.symbol] = summary.get(signal.symbol, 0) + 1
        return summary


class SignalFilter:
    """Additional filters that can be applied to entry signals."""

    @staticmethod
    def filter_by_strength(
        signals: List[EntrySignal], min_strength: float = 50.0
    ) -> List[EntrySignal]:
        """Filter signals by minimum strength score."""
        return [s for s in signals if s.signal_strength >= min_strength]

    @staticmethod
    def filter_by_symbol(
        signals: List[EntrySignal], symbols: List[str]
    ) -> List[EntrySignal]:
        """Filter signals to specific symbols."""
        symbol_set = set(symbols)
        return [s for s in signals if s.symbol in symbol_set]

    @staticmethod
    def rank_signals(signals: List[EntrySignal]) -> List[EntrySignal]:
        """Rank signals by strength (highest first)."""
        return sorted(signals, key=lambda s: s.signal_strength, reverse=True)

    @staticmethod
    def limit_signals(
        signals: List[EntrySignal], max_signals: int
    ) -> List[EntrySignal]:
        """Limit to top N signals by strength."""
        ranked = SignalFilter.rank_signals(signals)
        return ranked[:max_signals]


__all__ = ["SignalGenerator", "SignalFilter"]
