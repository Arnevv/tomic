"""P&L estimation model for backtesting without bid/ask data.

Since we don't have historical bid/ask or Greeks data, we estimate P&L
based on IV changes and time decay. This is a simplification that focuses
on the core thesis: does IV mean reversion work for premium selling?

The model uses the following principles:
1. Short premium strategies profit when IV decreases (vega exposure)
2. Short premium strategies profit from time decay (theta exposure)
3. Delta-neutral strategies have limited directional risk initially
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from tomic.backtest.config import BacktestConfig, CostConfig
from tomic.backtest.results import IVDataPoint


@dataclass
class PnLEstimate:
    """Estimated P&L breakdown for a position."""

    total_pnl: float
    vega_pnl: float  # P&L from IV change
    theta_pnl: float  # P&L from time decay
    costs: float  # Transaction costs
    pnl_pct: float  # P&L as percentage of max risk


class IronCondorPnLModel:
    """P&L estimation model for Iron Condor positions.

    Iron Condor characteristics:
    - Delta neutral at entry
    - Short vega (profits when IV decreases)
    - Positive theta (profits from time decay)
    - Limited max profit (credit received)
    - Limited max loss (wing width - credit)

    Model approach:
    Since we don't have Greeks, we model P&L as a function of:
    1. IV change since entry (vega component)
    2. Time elapsed as fraction of DTE (theta component)
    3. A simplified relationship between these factors

    Calibration notes:
    - Vega sensitivity: ~$1-2 per vol point per contract for typical IC
    - Theta: Accelerates as expiration approaches
    - We use conservative estimates to avoid overfitting
    """

    # Model parameters (can be calibrated with real trade data)
    # Conservative estimates to avoid overly optimistic backtests
    VEGA_SENSITIVITY = 1.0  # $ per vol point per $100 max risk (was 1.5)
    THETA_DECAY_FACTOR = 0.4  # Fraction of credit captured by theta over full DTE (was 0.6)
    MAX_PROFIT_CAPTURE = 0.50  # Target 50% of max profit

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.costs_config = config.costs

    def estimate_credit(
        self,
        iv_at_entry: float,
        max_risk: float,
        target_dte: int,
    ) -> float:
        """Estimate credit received for an Iron Condor.

        For a typical Iron Condor with ~0.16 delta short strikes:
        - Credit is roughly 25-35% of wing width
        - Higher IV = higher credit

        Args:
            iv_at_entry: ATM IV at entry (as decimal, e.g., 0.20 for 20%)
            max_risk: Maximum risk in dollars
            target_dte: Days to expiration at entry

        Returns:
            Estimated credit received in dollars.
        """
        # Base credit ratio (credit / max_risk) at 20% IV, 45 DTE
        base_credit_ratio = 0.30

        # Adjust for IV level (higher IV = higher credit)
        # Normalize IV to typical range
        iv_normalized = iv_at_entry if iv_at_entry < 1 else iv_at_entry / 100
        iv_adjustment = iv_normalized / 0.20  # Scale relative to 20% IV

        # Adjust for DTE (more DTE = higher credit due to more time value)
        dte_adjustment = min(1.2, target_dte / 45)

        credit_ratio = base_credit_ratio * iv_adjustment * dte_adjustment
        credit_ratio = min(0.50, max(0.15, credit_ratio))  # Cap between 15-50%

        return max_risk * credit_ratio

    def estimate_pnl(
        self,
        iv_at_entry: float,
        iv_current: float,
        days_in_trade: int,
        target_dte: int,
        estimated_credit: float,
        max_risk: float,
    ) -> PnLEstimate:
        """Estimate current P&L for an open Iron Condor position.

        Args:
            iv_at_entry: ATM IV at entry
            iv_current: Current ATM IV
            days_in_trade: Days since entry
            target_dte: Original DTE at entry
            estimated_credit: Credit received at entry
            max_risk: Maximum risk

        Returns:
            PnLEstimate with breakdown of P&L components.
        """
        # Normalize IV values
        iv_entry_norm = iv_at_entry if iv_at_entry < 1 else iv_at_entry / 100
        iv_current_norm = iv_current if iv_current < 1 else iv_current / 100

        # Calculate IV change in vol points
        iv_change = (iv_entry_norm - iv_current_norm) * 100  # In vol points

        # Vega P&L: profit when IV decreases
        # Scale by max_risk since vega exposure scales with position size
        vega_pnl = iv_change * self.VEGA_SENSITIVITY * (max_risk / 100)

        # Theta P&L: profit from time decay
        # Theta accelerates as expiration approaches
        # Model: theta capture = credit * time_fraction * decay_factor
        remaining_dte = max(0, target_dte - days_in_trade)
        time_fraction = days_in_trade / target_dte if target_dte > 0 else 0

        # Theta is not linear - it accelerates. Use sqrt for approximation.
        # sqrt(0.5) = 0.71, so at halfway point we've captured ~71% of theoretical theta
        theta_progress = time_fraction ** 0.5 if time_fraction > 0 else 0
        theta_pnl = estimated_credit * theta_progress * self.THETA_DECAY_FACTOR

        # Calculate costs (apply at entry)
        # For IC: 4 legs, so 4 contracts minimum
        num_contracts = max(1, int(max_risk / self.config.iron_condor_wing_width / 100))
        costs = self._calculate_costs(num_contracts * 4)

        # Total P&L
        total_pnl = vega_pnl + theta_pnl - costs

        # Cap at max profit (credit) and max loss
        total_pnl = min(estimated_credit, total_pnl)
        total_pnl = max(-max_risk, total_pnl)

        pnl_pct = (total_pnl / max_risk * 100) if max_risk > 0 else 0

        return PnLEstimate(
            total_pnl=round(total_pnl, 2),
            vega_pnl=round(vega_pnl, 2),
            theta_pnl=round(theta_pnl, 2),
            costs=round(costs, 2),
            pnl_pct=round(pnl_pct, 2),
        )

    def estimate_exit_pnl(
        self,
        iv_at_entry: float,
        iv_at_exit: float,
        days_in_trade: int,
        target_dte: int,
        estimated_credit: float,
        max_risk: float,
        exit_reason: str,
    ) -> float:
        """Estimate final P&L at exit.

        This is similar to estimate_pnl but applies exit-specific logic:
        - Profit target: Cap at target percentage
        - Stop loss: Apply full loss
        - Time-based exits: Use current estimated P&L
        """
        pnl_estimate = self.estimate_pnl(
            iv_at_entry=iv_at_entry,
            iv_current=iv_at_exit,
            days_in_trade=days_in_trade,
            target_dte=target_dte,
            estimated_credit=estimated_credit,
            max_risk=max_risk,
        )

        # Apply exit-specific adjustments
        if exit_reason == "profit_target":
            # Cap at profit target (50% of credit)
            target_profit = estimated_credit * (self.config.exit_rules.profit_target_pct / 100)
            return min(pnl_estimate.total_pnl, target_profit)

        elif exit_reason == "stop_loss":
            # Apply stop loss
            stop_loss = estimated_credit * (self.config.exit_rules.stop_loss_pct / 100)
            return max(pnl_estimate.total_pnl, -stop_loss)

        elif exit_reason == "iv_collapse":
            # IV collapsed - likely profitable, use estimate
            return max(0, pnl_estimate.total_pnl)

        else:
            # Other exits (DTE, DIT, delta breach): use estimate
            return pnl_estimate.total_pnl

    def _calculate_costs(self, num_legs: int) -> float:
        """Calculate transaction costs for a trade.

        Args:
            num_legs: Number of option legs in the trade

        Returns:
            Total costs in dollars.
        """
        commission = num_legs * self.costs_config.commission_per_contract
        # Slippage is calculated later as percentage of credit
        return commission


class SimplePnLModel:
    """Simplified P&L model for binary outcome analysis.

    This model treats trades as having binary outcomes:
    - Win: Capture X% of credit (default 50%)
    - Loss: Lose Y% of credit (default 100%)

    Useful for quick scenario analysis and validation.
    """

    def __init__(
        self,
        win_capture_pct: float = 50.0,
        loss_pct: float = 100.0,
    ):
        self.win_capture_pct = win_capture_pct
        self.loss_pct = loss_pct

    def estimate_win_pnl(self, estimated_credit: float) -> float:
        """Calculate P&L for a winning trade."""
        return estimated_credit * (self.win_capture_pct / 100)

    def estimate_loss_pnl(self, estimated_credit: float) -> float:
        """Calculate P&L for a losing trade."""
        return -estimated_credit * (self.loss_pct / 100)


__all__ = ["IronCondorPnLModel", "SimplePnLModel", "PnLEstimate"]
