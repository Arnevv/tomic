"""Liquidity filtering and scoring for backtesting.

This module provides tools to filter and score option strategies
based on liquidity metrics (volume, open interest, bid-ask spread).

Key components:
- LiquidityFilter: Filter iron condors based on liquidity rules
- LiquidityMetrics: Aggregate liquidity statistics for a trade
- calculate_execution_cost: Estimate real execution cost with slippage
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple, List

from tomic.backtest.config import LiquidityRulesConfig
from tomic.backtest.option_chain_loader import IronCondorQuotes, OptionQuote
from tomic.logutils import logger


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


class LiquidityFilter:
    """Filter and score option strategies based on liquidity.

    This class applies configurable liquidity rules to iron condors
    and other option structures. It can operate in three modes:

    - 'hard': Reject trades that don't meet thresholds
    - 'soft': Allow trades but penalize signal strength
    - 'off': No filtering (legacy behavior)
    """

    def __init__(self, config: LiquidityRulesConfig):
        self.config = config

    def filter_iron_condor(
        self,
        quotes: IronCondorQuotes,
    ) -> Tuple[bool, List[str], LiquidityMetrics]:
        """Filter an iron condor based on liquidity rules.

        Args:
            quotes: IronCondorQuotes with all four legs

        Returns:
            Tuple of:
            - passes: True if trade passes liquidity filter
            - reasons: List of rejection reasons (empty if passes)
            - metrics: LiquidityMetrics with detailed statistics
        """
        if self.config.mode == "off":
            # Return basic metrics without filtering
            metrics = self._calculate_metrics(quotes)
            return True, [], metrics

        metrics = self._calculate_metrics(quotes)
        reasons: List[str] = []

        # Check minimum volume per leg
        if metrics.min_volume < self.config.min_volume_per_leg:
            reasons.append(
                f"Min volume {metrics.min_volume} < {self.config.min_volume_per_leg}"
            )

        # Check minimum open interest per leg
        if metrics.min_open_interest < self.config.min_open_interest_per_leg:
            reasons.append(
                f"Min OI {metrics.min_open_interest} < {self.config.min_open_interest_per_leg}"
            )

        # Check maximum spread percentage
        if metrics.max_spread_pct > self.config.max_spread_pct:
            reasons.append(
                f"Max spread {metrics.max_spread_pct:.1f}% > {self.config.max_spread_pct}%"
            )

        # Check minimum liquidity score
        if metrics.min_liquidity_score < self.config.min_liquidity_score:
            reasons.append(
                f"Min liquidity score {metrics.min_liquidity_score:.1f} < {self.config.min_liquidity_score}"
            )

        # In hard mode, any failure rejects the trade
        if self.config.mode == "hard":
            passes = len(reasons) == 0
        else:
            # Soft mode: always passes but with warnings logged
            passes = True
            if reasons:
                logger.debug(f"Soft filter warnings: {', '.join(reasons)}")

        return passes, reasons, metrics

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
            if (leg.volume or 0) < self.config.min_volume_per_leg:
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
        if metrics.min_volume < self.config.min_volume_per_leg * 2:
            vol_ratio = metrics.min_volume / (self.config.min_volume_per_leg * 2)
            penalty *= 0.7 + (0.3 * vol_ratio)

        # Penalize low open interest (up to 30% reduction)
        if metrics.min_open_interest < self.config.min_open_interest_per_leg * 2:
            oi_ratio = metrics.min_open_interest / (self.config.min_open_interest_per_leg * 2)
            penalty *= 0.7 + (0.3 * oi_ratio)

        # Penalize wide spreads (up to 40% reduction)
        if metrics.max_spread_pct > self.config.max_spread_pct / 2:
            # Linear penalty from half threshold to threshold
            spread_excess = (metrics.max_spread_pct - self.config.max_spread_pct / 2) / (self.config.max_spread_pct / 2)
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
) -> Tuple[bool, List[str]]:
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
]
