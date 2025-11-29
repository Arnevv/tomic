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
from tomic.bs_calculator import calculate_greeks, OptionGreeks


@dataclass
class PnLEstimate:
    """Estimated P&L breakdown for a position."""

    total_pnl: float
    vega_pnl: float  # P&L from IV change
    theta_pnl: float  # P&L from time decay
    costs: float  # Transaction costs
    pnl_pct: float  # P&L as percentage of max risk


@dataclass
class GreeksSnapshot:
    """Greeks for a position at a point in time."""

    delta: float
    gamma: float
    vega: float
    theta: float
    position_price: float  # Price of entire IC position


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
        - Credit is roughly 25-40% of wing width
        - Higher IV = higher credit

        Args:
            iv_at_entry: ATM IV at entry (as decimal, e.g., 0.20 for 20%)
            max_risk: Maximum risk in dollars (not used, kept for API compatibility)
            target_dte: Days to expiration at entry

        Returns:
            Estimated credit received in dollars.
        """
        # Use wing width as the basis for credit calculation
        # This ensures R/R ratios are realistic
        wing_width = self.config.iron_condor_wing_width * 100  # e.g., $500 for $5 wings

        # Base credit ratio (credit / wing_width) at 20% IV, 45 DTE
        # Typical IC gets 25-35% of wing width as credit
        base_credit_ratio = 0.30

        # Adjust for IV level (higher IV = higher credit)
        # Normalize IV to typical range
        iv_normalized = iv_at_entry if iv_at_entry < 1 else iv_at_entry / 100
        iv_adjustment = iv_normalized / 0.20  # Scale relative to 20% IV

        # Adjust for DTE (more DTE = higher credit due to more time value)
        dte_adjustment = min(1.2, target_dte / 45)

        credit_ratio = base_credit_ratio * iv_adjustment * dte_adjustment
        # Cap between 20-50% of wing width
        # 40%+ credit = R/R <= 1.5 (TOMIC threshold)
        credit_ratio = min(0.50, max(0.20, credit_ratio))

        return wing_width * credit_ratio

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


class GreeksBasedPnLModel:
    """P&L estimation model using Black-Scholes Greeks.

    This model uses real option Greeks from Black-Scholes to calculate:
    1. Entry credit: Sum of short put spread + short call spread premiums
    2. Daily P&L: Track Greeks changes as IV and spot move
    3. Exit P&L: Final realized P&L from Greeks snapshots

    Iron Condor structure:
    - Short: 1x OTM Put + 1x OTM Call (wider spread)
    - Long: 1x ITM Put + 1x ITM Call (tighter spread)
    - This creates a 4-leg position with bounded risk/reward
    """

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.costs_config = config.costs

    def calculate_ic_greeks(
        self,
        spot_price: float,
        atm_iv: float,
        dte: int,
        short_put_delta: float = 0.20,
        short_call_delta: float = 0.20,
    ) -> GreeksSnapshot:
        """Calculate Greeks for entry and exit strikes of an Iron Condor.

        For simplicity, we calculate:
        - Short put at (spot - 1.5*atm*spot) or ~0.20 delta
        - Long put at (spot - 2.5*atm*spot) or lower
        - Short call at (spot + 1.5*atm*spot) or ~0.20 delta
        - Long call at (spot + 2.5*atm*spot) or higher

        Args:
            spot_price: Current spot price
            atm_iv: At-the-money IV
            dte: Days to expiration
            short_put_delta: Target delta for short put (typically 0.15-0.25)
            short_call_delta: Target delta for short call (typically 0.15-0.25)

        Returns:
            GreeksSnapshot with aggregated Greeks for the Iron Condor position
        """
        # Normalize IV
        iv = atm_iv if atm_iv < 1 else atm_iv / 100

        # Estimate strikes based on IV and delta
        # For 0.20 delta, strike is roughly spot - 0.85*iv*spot
        put_width = 0.85 * iv * spot_price  # Distance from ATM
        call_width = 0.85 * iv * spot_price

        short_put_strike = spot_price - put_width
        long_put_strike = short_put_strike - (iv * spot_price)  # Wing width
        short_call_strike = spot_price + call_width
        long_call_strike = short_call_strike + (iv * spot_price)  # Wing width

        # Calculate Greeks for each leg
        short_put_greeks = calculate_greeks("P", spot_price, short_put_strike, dte, iv)
        long_put_greeks = calculate_greeks("P", spot_price, long_put_strike, dte, iv)
        short_call_greeks = calculate_greeks("C", spot_price, short_call_strike, dte, iv)
        long_call_greeks = calculate_greeks("C", spot_price, long_call_strike, dte, iv)

        # Iron Condor: short 1 spread, long 1 spread = net credit position
        # Greeks are aggregated (short legs negative, long legs positive)
        delta = -short_put_greeks.delta + long_put_greeks.delta - short_call_greeks.delta + long_call_greeks.delta
        gamma = -short_put_greeks.gamma + long_put_greeks.gamma - short_call_greeks.gamma + long_call_greeks.gamma
        vega = -short_put_greeks.vega + long_put_greeks.vega - short_call_greeks.vega + long_call_greeks.vega
        theta = -short_put_greeks.theta + long_put_greeks.theta - short_call_greeks.theta + long_call_greeks.theta

        # Price is the credit received (sum of shorts minus longs)
        position_price = (
            (short_put_greeks.price - long_put_greeks.price)
            + (short_call_greeks.price - long_call_greeks.price)
        )

        # Apply multiplier (100 for US equity options)
        multiplier = 100
        vega_per_contract = vega / multiplier  # Vega is per 1% IV, scale to contract
        theta_per_contract = theta  # Theta is already per day

        return GreeksSnapshot(
            delta=delta,
            gamma=gamma,
            vega=vega_per_contract,
            theta=theta_per_contract,
            position_price=max(position_price * multiplier, 0.01),  # Avoid zero credit
        )

    def estimate_credit_from_greeks(
        self,
        spot_price: float,
        atm_iv: float,
        dte: int,
        max_risk: float,
    ) -> float:
        """Estimate credit received for Iron Condor using Greeks.

        Args:
            spot_price: Current spot price
            atm_iv: At-the-money IV
            dte: Days to expiration
            max_risk: Maximum risk per trade (wing width)

        Returns:
            Estimated credit in dollars
        """
        greeks_entry = self.calculate_ic_greeks(spot_price, atm_iv, dte)
        credit = greeks_entry.position_price

        # Wing width is typically max_risk (e.g., $200)
        # Scale credit to this risk level
        # For typical ICs, credit is 25-35% of wing width
        credit_ratio = max(0.15, min(0.50, credit / (max_risk / 2)))
        estimated_credit = max_risk * credit_ratio

        return max(estimated_credit, 1.0)

    def estimate_pnl_from_greeks(
        self,
        greeks_entry: GreeksSnapshot,
        greeks_current: GreeksSnapshot,
        days_in_trade: int,
        estimated_credit: float,
        max_risk: float,
        spot_at_entry: float,
        spot_current: float,
    ) -> PnLEstimate:
        """Estimate P&L using Greeks changes (vega and gamma P&L).

        P&L drivers:
        1. Vega P&L: Greeks_entry.vega * (IV_change) * multiplier
        2. Gamma P&L: 0.5 * Greeks_entry.gamma * (spot_change)^2 * multiplier
        3. Theta P&L: Greeks_entry.theta * days_in_trade * multiplier

        Args:
            greeks_entry: Greeks snapshot at entry
            greeks_current: Greeks snapshot at current point
            days_in_trade: Days elapsed
            estimated_credit: Credit received at entry
            max_risk: Maximum risk
            spot_at_entry: Spot price at entry
            spot_current: Current spot price

        Returns:
            PnLEstimate with P&L breakdown
        """
        # Spot move
        spot_move = spot_current - spot_at_entry

        # Gamma P&L: 0.5 * gamma * spot_move^2
        # Approximate using Greeks_entry (slightly conservative)
        gamma_pnl = 0.5 * greeks_entry.gamma * (spot_move ** 2) * 100

        # Theta P&L: theta per day * days_in_trade
        # Use average of entry and current theta
        avg_theta = (greeks_entry.theta + greeks_current.theta) / 2
        theta_pnl = avg_theta * days_in_trade * 100

        # Vega P&L: vega * iv_change
        # This is captured in greeks movement
        vega_pnl = (greeks_current.vega - greeks_entry.vega) * 100

        # Transaction costs
        num_contracts = max(1, int(max_risk / self.config.iron_condor_wing_width / 100))
        costs = self._calculate_costs(num_contracts * 4)

        # Total P&L
        total_pnl = gamma_pnl + theta_pnl + vega_pnl - costs

        # Cap at max profit and max loss
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

    def _calculate_costs(self, num_legs: int) -> float:
        """Calculate transaction costs for a trade."""
        commission = num_legs * self.costs_config.commission_per_contract
        return commission


__all__ = ["IronCondorPnLModel", "SimplePnLModel", "PnLEstimate", "GreeksBasedPnLModel", "GreeksSnapshot"]
