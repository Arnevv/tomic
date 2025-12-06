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
        earnings_data: Optional[Dict[str, date]] = None,
    ) -> List[EntrySignal]:
        """Scan all symbols for entry signals on a given date.

        Args:
            iv_data: Dictionary of symbol -> IVTimeSeries
            trading_date: Date to check for signals
            open_positions: Dict of symbol -> True if position is open
            earnings_data: Dict of symbol -> next earnings date (optional)

        Returns:
            List of EntrySignal objects for symbols meeting criteria.
        """
        signals = []
        earnings_data = earnings_data or {}

        for symbol, ts in iv_data.items():
            # Skip if we already have a position in this symbol
            if open_positions.get(symbol, False):
                continue

            # Get IV data for this date
            data_point = ts.get(trading_date)
            if data_point is None or not data_point.is_valid():
                continue

            # Check earnings constraint
            next_earnings = earnings_data.get(symbol)
            if not self._check_earnings_constraint(trading_date, next_earnings):
                continue

            # Check if entry criteria are met
            signal = self._evaluate_entry(data_point)
            if signal is not None:
                signals.append(signal)

        return signals

    def _check_earnings_constraint(
        self, trading_date: date, next_earnings: Optional[date]
    ) -> bool:
        """Check if earnings constraint is satisfied.

        Args:
            trading_date: Current trading date
            next_earnings: Next earnings date for the symbol (None if unknown)

        Returns:
            True if constraint is satisfied, False if entry should be rejected.
        """
        if next_earnings is None:
            return True  # No earnings data - allow entry

        rules = self.entry_rules
        min_days = rules.min_days_until_earnings

        if min_days is not None and min_days > 0:
            days_until = (next_earnings - trading_date).days
            if days_until < min_days:
                return False  # Too close to earnings

        return True

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


class CalendarSignalGenerator:
    """Generates entry signals for Calendar Spread trades.

    Calendar spreads have INVERSE entry criteria compared to Iron Condors:
    - Enter when IV is LOW (calendars are vega long)
    - Enter when term structure shows mispricing (front >= back)

    TOMIC Philosophy:
    - Calendars are VOLATILITY MISPRICING trades, not theta trades
    - Entry when IV percentile <= 40% (vega long profits from IV rise)
    - Entry when term_m1_m2 >= 0 (front-month IV >= back-month = mispricing)
    """

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.entry_rules = config.entry_rules

    def scan_for_signals(
        self,
        iv_data: Dict[str, IVTimeSeries],
        trading_date: date,
        open_positions: Dict[str, bool],
        earnings_data: Optional[Dict[str, date]] = None,
    ) -> List[EntrySignal]:
        """Scan all symbols for calendar entry signals on a given date.

        Args:
            iv_data: Dictionary of symbol -> IVTimeSeries
            trading_date: Date to check for signals
            open_positions: Dict of symbol -> True if position is open
            earnings_data: Dict of symbol -> next earnings date (optional)

        Returns:
            List of EntrySignal objects for symbols meeting calendar criteria.
        """
        signals = []
        earnings_data = earnings_data or {}

        for symbol, ts in iv_data.items():
            # Skip if we already have a position in this symbol
            if open_positions.get(symbol, False):
                continue

            # Get IV data for this date
            data_point = ts.get(trading_date)
            if data_point is None or not data_point.is_valid():
                continue

            # Check earnings constraint
            next_earnings = earnings_data.get(symbol)
            if not self._check_earnings_constraint(trading_date, next_earnings):
                continue

            # Check if calendar entry criteria are met
            signal = self._evaluate_calendar_entry(data_point)
            if signal is not None:
                signals.append(signal)

        return signals

    def _check_earnings_constraint(
        self, trading_date: date, next_earnings: Optional[date]
    ) -> bool:
        """Check if earnings constraint is satisfied.

        Args:
            trading_date: Current trading date
            next_earnings: Next earnings date for the symbol (None if unknown)

        Returns:
            True if constraint is satisfied, False if entry should be rejected.
        """
        if next_earnings is None:
            return True  # No earnings data - allow entry

        rules = self.entry_rules
        min_days = rules.min_days_until_earnings

        if min_days is not None and min_days > 0:
            days_until = (next_earnings - trading_date).days
            if days_until < min_days:
                return False  # Too close to earnings

        return True

    def _evaluate_calendar_entry(self, dp: IVDataPoint) -> Optional[EntrySignal]:
        """Evaluate if a data point meets calendar entry criteria.

        Calendar Entry Criteria (from volatility_rules.yaml):
        - iv_rank <= 0.4 (40%)
        - iv_percentile <= 0.4 (40%)
        - term_m1_m2 >= 0 (front-month IV >= back-month IV)

        Args:
            dp: IVDataPoint to evaluate

        Returns:
            EntrySignal if criteria are met, None otherwise.
        """
        rules = self.entry_rules

        # Primary check: IV percentile MAXIMUM (opposite of Iron Condor)
        if dp.iv_percentile is None:
            return None

        # Calendar needs LOW IV (vega long position)
        iv_percentile_max = rules.iv_percentile_max
        if iv_percentile_max is None:
            iv_percentile_max = 40.0  # Default from volatility_rules.yaml

        # Normalize iv_percentile if needed (could be 0-100 or 0-1)
        iv_pct = dp.iv_percentile
        if iv_pct > 1:
            iv_pct = iv_pct / 100  # Convert to decimal

        if iv_pct > iv_percentile_max / 100 if iv_percentile_max > 1 else iv_percentile_max:
            return None

        # Optional: IV rank maximum
        iv_rank_max = rules.iv_rank_max
        if iv_rank_max is not None and dp.iv_rank is not None:
            iv_rank = dp.iv_rank
            if iv_rank > 1:
                iv_rank = iv_rank / 100  # Normalize
            iv_rank_threshold = iv_rank_max / 100 if iv_rank_max > 1 else iv_rank_max
            if iv_rank > iv_rank_threshold:
                return None

        # Term structure filter: front-month IV >= back-month IV (mispricing)
        term = dp.term_m1_m2  # M1-M2 term structure
        term_min = rules.term_structure_min
        if term_min is not None and term is not None:
            if term < term_min:
                return None

        # Optional: Term structure maximum
        if rules.term_structure_max is not None and term is not None:
            if term > rules.term_structure_max:
                return None

        # All criteria met - calculate signal strength
        signal_strength = self._calculate_calendar_signal_strength(dp)

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

    def _calculate_calendar_signal_strength(self, dp: IVDataPoint) -> float:
        """Calculate composite signal strength for calendar entry (0-100).

        For calendars, stronger signals come from:
        - LOWER IV percentile (more room for IV to rise)
        - HIGHER term structure spread (bigger mispricing)
        """
        score = 0.0
        weights_used = 0.0

        # IV percentile contribution (0-50 points)
        # Lower IV = stronger signal for calendar
        if dp.iv_percentile is not None:
            iv_pct = dp.iv_percentile
            if iv_pct > 1:
                iv_pct = iv_pct / 100
            # Scale: 0% = 50 points, 40% = 0 points (inverted from IC)
            pct_score = max(0, (0.40 - iv_pct) / 0.40) * 50
            score += pct_score
            weights_used += 50

        # Term structure contribution (0-30 points)
        # Higher term spread = bigger mispricing = stronger signal
        if dp.term_m1_m2 is not None:
            term = dp.term_m1_m2
            # Scale: 0 = 0 points, 5+ vol points = 30 points
            term_score = min(30, max(0, term / 5.0) * 30)
            score += term_score
            weights_used += 30

        # IV rank contribution (0-20 points)
        # Lower IV rank = stronger signal for calendar
        if dp.iv_rank is not None:
            iv_rank = dp.iv_rank
            if iv_rank > 1:
                iv_rank = iv_rank / 100
            # Scale: 0% = 20 points, 40% = 0 points
            rank_score = max(0, (0.40 - iv_rank) / 0.40) * 20
            score += rank_score
            weights_used += 20

        # Normalize to 0-100 scale
        if weights_used > 0:
            score = (score / weights_used) * 100

        return round(score, 2)


__all__ = ["SignalGenerator", "SignalFilter", "CalendarSignalGenerator"]
