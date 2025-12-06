"""Liquidity filtering for backtesting.

This module provides tools to filter option strategies based on liquidity metrics
(volume, open interest, bid-ask spread). It reuses the existing check_liquidity
function from analysis/scoring.py for consistency with the normal pipeline.

Key components:
- LiquidityFilter: Filter iron condors based on liquidity rules
- LiquidityMetrics: Aggregate liquidity statistics for a trade
- iron_condor_to_legs: Convert IronCondorQuotes to leg dicts for check_liquidity
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from tomic.backtest.config import LiquidityRulesConfig
from tomic.backtest.option_chain_loader import (
    CalendarSpreadQuotes,
    IronCondorQuotes,
    OptionQuote,
)
from tomic.logutils import logger

# Import the existing check_liquidity function and reason helpers
from tomic.analysis.scoring import check_liquidity
from tomic.strategy.reasons import ReasonDetail, ReasonCategory, make_reason


class _MarketDataAdapter:
    """Adapter to provide market_data interface for check_liquidity.

    This allows the backtest LiquidityRulesConfig to work with the
    existing check_liquidity function which expects crit.market_data.
    """

    def __init__(self, min_option_volume: int, min_option_open_interest: int):
        self.min_option_volume = min_option_volume
        self.min_option_open_interest = min_option_open_interest


class _CriteriaAdapter:
    """Adapter to provide CriteriaConfig interface for check_liquidity.

    The check_liquidity function only uses crit.market_data, so we provide
    a minimal adapter that exposes just that property.
    """

    def __init__(self, market_data: _MarketDataAdapter):
        self.market_data = market_data


@dataclass
class LiquidityMetrics:
    """Aggregate liquidity metrics for an option structure."""

    # Per-leg minimums (weakest link)
    min_volume: int
    min_open_interest: int
    max_spread_pct: float

    # Aggregate scores
    min_liquidity_score: float
    avg_liquidity_score: float

    # Total spread cost (in dollars)
    total_spread_cost: float

    # Execution impact
    realistic_entry_credit: Optional[float]
    mid_entry_credit: Optional[float]
    slippage_cost: Optional[float]

    # Warning flags
    low_volume_legs: List[str]
    high_spread_legs: List[str]

    @property
    def passes_basic_check(self) -> bool:
        """Quick check if metrics look reasonable."""
        return (
            self.min_volume > 0
            and self.min_open_interest > 0
            and self.max_spread_pct < 50
        )

    @property
    def slippage_pct(self) -> Optional[float]:
        """Slippage as percentage of mid credit."""
        if self.slippage_cost and self.mid_entry_credit:
            return (self.slippage_cost / self.mid_entry_credit) * 100
        return None


def iron_condor_to_legs(quotes: IronCondorQuotes) -> List[Dict[str, Any]]:
    """Convert IronCondorQuotes to leg dictionaries for check_liquidity.

    This ensures compatibility with the existing pipeline's check_liquidity function.
    """
    if not quotes.is_complete:
        return []

    legs = []
    for name, quote in [
        ("long_put", quotes.long_put),
        ("short_put", quotes.short_put),
        ("short_call", quotes.short_call),
        ("long_call", quotes.long_call),
    ]:
        leg = {
            "strike": quote.strike,
            "expiry": str(quote.expiry),
            "volume": quote.volume,
            "open_interest": quote.open_interest,
            "bid": quote.bid,
            "ask": quote.ask,
            "mid": quote.mid,
            "delta": quote.delta,
            "type": quote.option_type,
            "position": -1 if "short" in name else 1,
        }
        legs.append(leg)

    return legs


def calendar_spread_to_legs(quotes: CalendarSpreadQuotes) -> List[Dict[str, Any]]:
    """Convert CalendarSpreadQuotes to leg dictionaries for check_liquidity.

    This ensures compatibility with the existing pipeline's check_liquidity function.
    """
    if not quotes.is_complete:
        return []

    legs = []
    for name, quote in [
        ("short_leg", quotes.short_leg),
        ("long_leg", quotes.long_leg),
    ]:
        leg = {
            "strike": quote.strike,
            "expiry": str(quote.expiry),
            "volume": quote.volume,
            "open_interest": quote.open_interest,
            "bid": quote.bid,
            "ask": quote.ask,
            "mid": quote.mid,
            "delta": quote.delta,
            "type": quote.option_type,
            "position": -1 if "short" in name else 1,
        }
        legs.append(leg)

    return legs


def _make_criteria_adapter(liquidity_rules: LiquidityRulesConfig) -> _CriteriaAdapter:
    """Create a CriteriaConfig adapter from LiquidityRulesConfig for check_liquidity.

    This bridges the backtest config to the existing pipeline's expected format.
    The check_liquidity function only uses crit.market_data, so we use a minimal
    adapter instead of requiring the full CriteriaConfig with all its fields.
    """
    market_data = _MarketDataAdapter(
        min_option_volume=liquidity_rules.min_option_volume,
        min_option_open_interest=liquidity_rules.min_option_open_interest,
    )
    return _CriteriaAdapter(market_data=market_data)


class LiquidityFilter:
    """Filter and score option strategies based on liquidity.

    This class applies configurable liquidity rules to iron condors
    and other option structures. It reuses the existing check_liquidity
    function from analysis/scoring.py for consistency.

    Modes:
    - 'hard': Reject trades that don't meet thresholds
    - 'soft': Allow trades but log warnings
    - 'off': No filtering (legacy behavior)
    """

    def __init__(self, config: LiquidityRulesConfig):
        self.config = config
        # Create adapter for the existing check_liquidity function
        self._criteria_adapter = _make_criteria_adapter(config)

    def filter_iron_condor(
        self,
        quotes: IronCondorQuotes,
        strategy_name: str = "iron_condor",
    ) -> Tuple[bool, List[ReasonDetail], LiquidityMetrics]:
        """Filter an iron condor based on liquidity rules.

        Uses the existing check_liquidity function from analysis/scoring.py
        for the core volume/OI check, plus additional spread checks.

        Args:
            quotes: IronCondorQuotes with all four legs
            strategy_name: Strategy name for logging (default: "iron_condor")

        Returns:
            Tuple of:
            - passes: True if trade passes liquidity filter
            - reasons: List of ReasonDetail objects (empty if passes)
            - metrics: LiquidityMetrics with detailed statistics
        """
        if self.config.mode == "off":
            # Return basic metrics without filtering
            metrics = self._calculate_metrics(quotes)
            return True, [], metrics

        metrics = self._calculate_metrics(quotes)
        reasons: List[ReasonDetail] = []

        # Convert to legs for the existing check_liquidity function
        legs = iron_condor_to_legs(quotes)

        if legs:
            # Use the existing check_liquidity function for volume/OI checks
            passes_vol_oi, vol_oi_reasons = check_liquidity(
                strategy_name, legs, self._criteria_adapter
            )
            if not passes_vol_oi:
                reasons.extend(vol_oi_reasons)

        # Additional spread check (backtest-specific)
        if self.config.max_spread_pct < 100:
            if metrics.max_spread_pct > self.config.max_spread_pct:
                reasons.append(
                    make_reason(
                        ReasonCategory.LOW_LIQUIDITY,
                        "WIDE_SPREAD",
                        f"bid-ask spread te breed ({metrics.max_spread_pct:.1f}% > {self.config.max_spread_pct}%)",
                        data={"max_spread_pct": metrics.max_spread_pct},
                    )
                )

        # Additional liquidity score check (backtest-specific)
        if self.config.min_liquidity_score > 0:
            if metrics.min_liquidity_score < self.config.min_liquidity_score:
                reasons.append(
                    make_reason(
                        ReasonCategory.LOW_LIQUIDITY,
                        "LOW_LIQUIDITY_SCORE",
                        f"liquiditeitsscore te laag ({metrics.min_liquidity_score:.1f} < {self.config.min_liquidity_score})",
                        data={"min_liquidity_score": metrics.min_liquidity_score},
                    )
                )

        # In hard mode, any failure rejects the trade
        if self.config.mode == "hard":
            passes = len(reasons) == 0
        else:
            # Soft mode: always passes but with warnings logged
            passes = True
            if reasons:
                reason_msgs = [r.message for r in reasons]
                logger.debug(f"Soft filter warnings: {', '.join(reason_msgs)}")

        return passes, reasons, metrics

    def filter_calendar_spread(
        self,
        quotes: CalendarSpreadQuotes,
        strategy_name: str = "calendar",
    ) -> Tuple[bool, List[ReasonDetail], LiquidityMetrics]:
        """Filter a calendar spread based on liquidity rules.

        Uses the existing check_liquidity function from analysis/scoring.py
        for the core volume/OI check, plus additional spread checks.

        Args:
            quotes: CalendarSpreadQuotes with both legs
            strategy_name: Strategy name for logging (default: "calendar")

        Returns:
            Tuple of:
            - passes: True if trade passes liquidity filter
            - reasons: List of ReasonDetail objects (empty if passes)
            - metrics: LiquidityMetrics with detailed statistics
        """
        if self.config.mode == "off":
            # Return basic metrics without filtering
            metrics = self._calculate_calendar_metrics(quotes)
            return True, [], metrics

        metrics = self._calculate_calendar_metrics(quotes)
        reasons: List[ReasonDetail] = []

        # Convert to legs for the existing check_liquidity function
        legs = calendar_spread_to_legs(quotes)

        if legs:
            # Use the existing check_liquidity function for volume/OI checks
            passes_vol_oi, vol_oi_reasons = check_liquidity(
                strategy_name, legs, self._criteria_adapter
            )
            if not passes_vol_oi:
                reasons.extend(vol_oi_reasons)

        # Additional spread check (backtest-specific)
        if self.config.max_spread_pct < 100:
            if metrics.max_spread_pct > self.config.max_spread_pct:
                reasons.append(
                    make_reason(
                        ReasonCategory.LOW_LIQUIDITY,
                        "WIDE_SPREAD",
                        f"bid-ask spread te breed ({metrics.max_spread_pct:.1f}% > {self.config.max_spread_pct}%)",
                        data={"max_spread_pct": metrics.max_spread_pct},
                    )
                )

        # Additional liquidity score check (backtest-specific)
        if self.config.min_liquidity_score > 0:
            if metrics.min_liquidity_score < self.config.min_liquidity_score:
                reasons.append(
                    make_reason(
                        ReasonCategory.LOW_LIQUIDITY,
                        "LOW_LIQUIDITY_SCORE",
                        f"liquiditeitsscore te laag ({metrics.min_liquidity_score:.1f} < {self.config.min_liquidity_score})",
                        data={"min_liquidity_score": metrics.min_liquidity_score},
                    )
                )

        # In hard mode, any failure rejects the trade
        if self.config.mode == "hard":
            passes = len(reasons) == 0
        else:
            # Soft mode: always passes but with warnings logged
            passes = True
            if reasons:
                reason_msgs = [r.message for r in reasons]
                logger.debug(f"Soft filter warnings (calendar): {', '.join(reason_msgs)}")

        return passes, reasons, metrics

    def _calculate_calendar_metrics(self, quotes: CalendarSpreadQuotes) -> LiquidityMetrics:
        """Calculate comprehensive liquidity metrics for a calendar spread."""
        if not quotes.is_complete:
            return LiquidityMetrics(
                min_volume=0,
                min_open_interest=0,
                max_spread_pct=100.0,
                min_liquidity_score=0.0,
                avg_liquidity_score=0.0,
                total_spread_cost=0.0,
                realistic_entry_credit=None,
                mid_entry_credit=None,
                slippage_cost=None,
                low_volume_legs=[],
                high_spread_legs=[],
            )

        legs = [
            ("short_leg", quotes.short_leg),
            ("long_leg", quotes.long_leg),
        ]

        # Collect per-leg metrics
        volumes = []
        ois = []
        spreads = []
        scores = []
        low_volume_legs = []
        high_spread_legs = []

        for name, leg in legs:
            volumes.append(leg.volume or 0)
            ois.append(leg.open_interest or 0)
            spreads.append(leg.spread_pct or 0)
            scores.append(leg.liquidity_score)

            # Track warning flags
            if (leg.volume or 0) < self.config.min_option_volume:
                low_volume_legs.append(f"{name} (vol={leg.volume or 0})")
            if (leg.spread_pct or 0) > self.config.max_spread_pct:
                high_spread_legs.append(f"{name} (spread={leg.spread_pct:.1f}%)")

        # Calculate execution costs (calendar is debit, not credit)
        mid_debit = quotes.net_debit
        realistic_debit = quotes.entry_debit_realistic()
        slippage = None
        if mid_debit is not None and realistic_debit is not None:
            # For debit trades, slippage increases cost (realistic > mid)
            slippage = realistic_debit - mid_debit

        return LiquidityMetrics(
            min_volume=min(volumes),
            min_open_interest=min(ois),
            max_spread_pct=max(spreads),
            min_liquidity_score=min(scores),
            avg_liquidity_score=sum(scores) / len(scores),
            total_spread_cost=quotes.total_spread_cost or 0.0,
            # For debit trades, we use negative values to indicate debit
            realistic_entry_credit=-realistic_debit if realistic_debit else None,
            mid_entry_credit=-mid_debit if mid_debit else None,
            slippage_cost=slippage,
            low_volume_legs=low_volume_legs,
            high_spread_legs=high_spread_legs,
        )

    def _calculate_metrics(self, quotes: IronCondorQuotes) -> LiquidityMetrics:
        """Calculate comprehensive liquidity metrics for an iron condor."""
        if not quotes.is_complete:
            return LiquidityMetrics(
                min_volume=0,
                min_open_interest=0,
                max_spread_pct=100.0,
                min_liquidity_score=0.0,
                avg_liquidity_score=0.0,
                total_spread_cost=0.0,
                realistic_entry_credit=None,
                mid_entry_credit=None,
                slippage_cost=None,
                low_volume_legs=[],
                high_spread_legs=[],
            )

        legs = [
            ("long_put", quotes.long_put),
            ("short_put", quotes.short_put),
            ("short_call", quotes.short_call),
            ("long_call", quotes.long_call),
        ]

        # Collect per-leg metrics
        volumes = []
        ois = []
        spreads = []
        scores = []
        low_volume_legs = []
        high_spread_legs = []

        for name, leg in legs:
            volumes.append(leg.volume or 0)
            ois.append(leg.open_interest or 0)
            spreads.append(leg.spread_pct or 0)
            scores.append(leg.liquidity_score)

            # Track warning flags
            if (leg.volume or 0) < self.config.min_option_volume:
                low_volume_legs.append(f"{name} (vol={leg.volume or 0})")
            if (leg.spread_pct or 0) > self.config.max_spread_pct:
                high_spread_legs.append(f"{name} (spread={leg.spread_pct:.1f}%)")

        # Calculate execution costs
        mid_credit = quotes.net_credit
        realistic_credit = quotes.entry_credit_realistic()
        slippage = None
        if mid_credit and realistic_credit:
            slippage = mid_credit - realistic_credit

        return LiquidityMetrics(
            min_volume=min(volumes),
            min_open_interest=min(ois),
            max_spread_pct=max(spreads),
            min_liquidity_score=min(scores),
            avg_liquidity_score=sum(scores) / len(scores),
            total_spread_cost=quotes.total_spread_cost or 0.0,
            realistic_entry_credit=realistic_credit,
            mid_entry_credit=mid_credit,
            slippage_cost=slippage,
            low_volume_legs=low_volume_legs,
            high_spread_legs=high_spread_legs,
        )

    def calculate_signal_penalty(self, metrics: LiquidityMetrics) -> float:
        """Calculate signal strength penalty based on liquidity.

        Returns a multiplier between 0.0 and 1.0 to apply to signal strength.
        1.0 = no penalty (excellent liquidity)
        0.0 = maximum penalty (very poor liquidity)
        """
        if self.config.mode == "off":
            return 1.0

        # Start with full signal strength
        penalty = 1.0

        # Penalize low volume (up to 30% reduction)
        if metrics.min_volume < self.config.min_option_volume * 2:
            vol_ratio = metrics.min_volume / max(1, self.config.min_option_volume * 2)
            penalty *= 0.7 + (0.3 * vol_ratio)

        # Penalize low open interest (up to 30% reduction)
        if metrics.min_open_interest < self.config.min_option_open_interest * 2:
            oi_ratio = metrics.min_open_interest / max(1, self.config.min_option_open_interest * 2)
            penalty *= 0.7 + (0.3 * oi_ratio)

        # Penalize wide spreads (up to 40% reduction)
        if metrics.max_spread_pct > self.config.max_spread_pct / 2:
            spread_excess = (metrics.max_spread_pct - self.config.max_spread_pct / 2) / max(1, self.config.max_spread_pct / 2)
            spread_excess = min(1.0, spread_excess)
            penalty *= 1.0 - (0.4 * spread_excess)

        return max(0.0, min(1.0, penalty))

    def estimate_execution_quality(
        self,
        quotes: IronCondorQuotes,
        position_size: int = 1,
    ) -> dict:
        """Estimate execution quality metrics.

        Args:
            quotes: IronCondorQuotes for the trade
            position_size: Number of contracts

        Returns:
            Dict with execution quality metrics
        """
        if not quotes.is_complete:
            return {"quality": "unknown", "warnings": ["Incomplete quotes"]}

        metrics = self._calculate_metrics(quotes)
        warnings = []

        # Check volume impact
        if metrics.min_volume > 0:
            volume_impact = position_size / metrics.min_volume
            if volume_impact > self.config.volume_impact_threshold:
                warnings.append(
                    f"Position size ({position_size}) is {volume_impact:.0%} of min volume"
                )

        # Estimate fill probability
        if metrics.min_liquidity_score >= 60:
            fill_probability = "high"
        elif metrics.min_liquidity_score >= 30:
            fill_probability = "medium"
        else:
            fill_probability = "low"

        # Estimate price improvement potential
        if metrics.max_spread_pct < 5:
            price_improvement = "likely"
        elif metrics.max_spread_pct < 15:
            price_improvement = "possible"
        else:
            price_improvement = "unlikely"

        return {
            "quality": fill_probability,
            "fill_probability": fill_probability,
            "price_improvement": price_improvement,
            "slippage_estimate": metrics.slippage_cost,
            "slippage_pct": metrics.slippage_pct,
            "warnings": warnings,
        }


def filter_by_liquidity(
    quotes: IronCondorQuotes,
    config: LiquidityRulesConfig,
) -> Tuple[bool, List[ReasonDetail]]:
    """Convenience function to filter an iron condor by liquidity.

    Args:
        quotes: IronCondorQuotes to filter
        config: LiquidityRulesConfig with filtering rules

    Returns:
        Tuple of (passes, rejection_reasons)
    """
    filter_instance = LiquidityFilter(config)
    passes, reasons, _ = filter_instance.filter_iron_condor(quotes)
    return passes, reasons


__all__ = [
    "LiquidityFilter",
    "LiquidityMetrics",
    "filter_by_liquidity",
    "iron_condor_to_legs",
    "calendar_spread_to_legs",
]
