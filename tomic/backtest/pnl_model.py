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
from datetime import date, timedelta
from typing import Any, Optional

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
    # Realistic estimates for iron condor P&L dynamics
    # Increased from conservative values (1.0/0.4) to more realistic values
    # to better model losses during IV spikes and normal theta decay
    VEGA_SENSITIVITY = 1.5  # $ per vol point per $100 max risk
    THETA_DECAY_FACTOR = 0.5  # Fraction of credit captured by theta over full DTE
    MAX_PROFIT_CAPTURE = 0.50  # Target 50% of max profit

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.costs_config = config.costs

    def estimate_credit(
        self,
        iv_at_entry: float,
        max_risk: float,
        target_dte: int,
        stddev_range: Optional[float] = None,
    ) -> float:
        """Estimate credit received for an Iron Condor.

        For a typical Iron Condor with ~0.16 delta short strikes:
        - Credit is roughly 25-40% of wing width
        - Higher IV = higher credit
        - Lower stddev_range = strikes closer to ATM = higher credit

        Args:
            iv_at_entry: ATM IV at entry (as decimal, e.g., 0.20 for 20%)
            max_risk: Maximum risk in dollars (not used, kept for API compatibility)
            target_dte: Days to expiration at entry
            stddev_range: Standard deviation distance for short strikes (default 1.5)
                Lower values = strikes closer to ATM = higher credit but higher risk
                Higher values = strikes farther from ATM = lower credit but lower risk

        Returns:
            Estimated credit received in dollars.
        """
        # Use wing width as the basis for credit calculation
        # This ensures R/R ratios are realistic
        wing_width = self.config.iron_condor_wing_width * 100  # e.g., $500 for $5 wings

        # Base credit ratio (credit / wing_width) at 20% IV, 45 DTE, 1.5 stddev
        # Typical IC gets 25-35% of wing width as credit
        base_credit_ratio = 0.30

        # Adjust for IV level (higher IV = higher credit)
        # Normalize IV to typical range
        # Use threshold of 2 to handle high-IV stocks (IV > 200% is unrealistic)
        iv_normalized = iv_at_entry if iv_at_entry <= 2 else iv_at_entry / 100
        iv_adjustment = iv_normalized / 0.20  # Scale relative to 20% IV

        # Adjust for DTE (more DTE = higher credit due to more time value)
        dte_adjustment = min(1.2, target_dte / 45)

        # Adjust for stddev_range (lower stddev = closer to ATM = higher credit)
        # At stddev 1.0: ~35% more credit than baseline
        # At stddev 1.5: baseline (no adjustment)
        # At stddev 2.0: ~25% less credit than baseline
        # At stddev 2.5: ~40% less credit than baseline
        if stddev_range is not None and stddev_range > 0:
            # stddev_adjustment: inverse relationship, normalized to 1.5 baseline
            # Formula: (1.5 / stddev_range) ^ 0.6 gives good scaling
            stddev_adjustment = (1.5 / stddev_range) ** 0.6
            # Cap the adjustment to reasonable bounds
            stddev_adjustment = min(1.5, max(0.5, stddev_adjustment))
        else:
            stddev_adjustment = 1.0

        credit_ratio = base_credit_ratio * iv_adjustment * dte_adjustment * stddev_adjustment
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
        # Use threshold of 2 to handle high-IV stocks (IV > 200% is unrealistic)
        iv_entry_norm = iv_at_entry if iv_at_entry <= 2 else iv_at_entry / 100
        iv_current_norm = iv_current if iv_current <= 2 else iv_current / 100

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
        spot_at_entry: Optional[float] = None,
        spot_at_exit: Optional[float] = None,
    ) -> float:
        """Estimate final P&L at exit.

        This is similar to estimate_pnl but applies exit-specific logic:
        - Profit target: Cap at target percentage
        - Stop loss: Apply full loss
        - Delta breach: Apply realistic loss based on spot movement
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

        elif exit_reason == "delta_breach":
            # Delta breach means the underlying moved significantly against us
            # This typically results in a loss, not a profit
            # Calculate realistic loss based on spot movement if available
            if spot_at_entry and spot_at_exit and spot_at_entry > 0:
                spot_move_pct = abs((spot_at_exit - spot_at_entry) / spot_at_entry) * 100

                # Loss scales with spot movement beyond expected range
                # At 5% move: ~50% of max risk loss
                # At 10% move: ~80% of max risk loss
                # At 15%+ move: approaching max loss
                loss_factor = min(1.0, spot_move_pct / 15.0) * 0.8 + 0.2

                # Apply loss (negative P&L)
                delta_breach_loss = -max_risk * loss_factor

                # But don't lose more than max_risk
                return max(delta_breach_loss, -max_risk)
            else:
                # No spot data: assume moderate loss (60% of max risk)
                return -max_risk * 0.6

        else:
            # Other exits (DTE, DIT): use estimate
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
        # Use threshold of 2 to handle high-IV stocks (IV > 200% is unrealistic)
        iv = atm_iv if atm_iv <= 2 else atm_iv / 100

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
        stddev_range: Optional[float] = None,
    ) -> float:
        """Estimate credit received for Iron Condor using Greeks.

        Args:
            spot_price: Current spot price
            atm_iv: At-the-money IV
            dte: Days to expiration
            max_risk: Maximum risk per trade (wing width)
            stddev_range: Standard deviation distance for short strikes (default 1.5)
                Lower values = strikes closer to ATM = higher credit but higher risk
                Higher values = strikes farther from ATM = lower credit but lower risk

        Returns:
            Estimated credit in dollars
        """
        greeks_entry = self.calculate_ic_greeks(spot_price, atm_iv, dte)
        credit = greeks_entry.position_price

        # Wing width is typically max_risk (e.g., $200)
        # Scale credit to this risk level
        # For typical ICs, credit is 25-35% of wing width
        credit_ratio = max(0.15, min(0.50, credit / (max_risk / 2)))

        # Adjust for stddev_range (lower stddev = closer to ATM = higher credit)
        if stddev_range is not None and stddev_range > 0:
            # stddev_adjustment: inverse relationship, normalized to 1.5 baseline
            stddev_adjustment = (1.5 / stddev_range) ** 0.6
            stddev_adjustment = min(1.5, max(0.5, stddev_adjustment))
            credit_ratio = credit_ratio * stddev_adjustment
            # Re-cap after adjustment
            credit_ratio = max(0.15, min(0.50, credit_ratio))

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


class RealPricesPnLModel:
    """P&L model using real option chain prices from ORATS.

    This model calculates actual P&L by:
    1. Looking up real bid/ask prices at entry
    2. Looking up real bid/ask prices at exit
    3. Applying realistic slippage (sell at bid, buy at ask)

    This provides the most accurate P&L estimation but requires
    historical option chain data to be available.
    """

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.costs_config = config.costs

        # Lazy import to avoid circular dependency
        self._chain_loader = None

    @property
    def chain_loader(self):
        """Lazy-load the option chain loader."""
        if self._chain_loader is None:
            from tomic.backtest.option_chain_loader import OptionChainLoader
            self._chain_loader = OptionChainLoader(
                use_real_prices=self.config.use_real_prices,
            )
        return self._chain_loader

    def get_entry_quotes(
        self,
        symbol: str,
        entry_date: date,
        target_dte: int,
        short_put_delta: float = -0.20,
        short_call_delta: float = 0.20,
        wing_width: float = 5.0,
    ) -> Optional[Any]:
        """Get iron condor quotes at entry.

        Args:
            symbol: Stock symbol
            entry_date: Trade entry date
            target_dte: Target days to expiration
            short_put_delta: Target delta for short put
            short_call_delta: Target delta for short call
            wing_width: Wing width in dollars

        Returns:
            IronCondorQuotes if found, None otherwise.
        """
        chain = self.chain_loader.load_chain(symbol, entry_date)
        if chain is None:
            return None

        # Find expiry closest to target DTE
        expiries = chain.get_expiries()
        target_expiry = entry_date + timedelta(days=target_dte)

        best_expiry = None
        best_diff = float('inf')
        for exp in expiries:
            diff = abs((exp - target_expiry).days)
            if diff < best_diff:
                best_diff = diff
                best_expiry = exp

        if best_expiry is None:
            return None

        # Select iron condor strikes
        return chain.select_iron_condor(
            expiry=best_expiry,
            short_put_delta=short_put_delta,
            short_call_delta=short_call_delta,
            wing_width=wing_width,
        )

    def get_exit_quotes(
        self,
        symbol: str,
        exit_date: date,
        entry_quotes: Any,
    ) -> Optional[Any]:
        """Get iron condor quotes at exit (same strikes as entry).

        Args:
            symbol: Stock symbol
            exit_date: Trade exit date
            entry_quotes: IronCondorQuotes from entry

        Returns:
            IronCondorQuotes at exit prices, or None if not available.
        """
        chain = self.chain_loader.load_chain(symbol, exit_date)
        if chain is None:
            return None

        from tomic.backtest.option_chain_loader import IronCondorQuotes

        # Find the same strikes in the exit chain
        expiry = entry_quotes.expiry
        options_at_expiry = chain.filter_by_expiry(expiry)

        if not options_at_expiry:
            return None

        # Build lookup by (strike, type)
        option_map = {
            (opt.strike, opt.option_type): opt
            for opt in options_at_expiry
        }

        # Find matching options
        long_put = option_map.get((entry_quotes.long_put.strike, 'P'))
        short_put = option_map.get((entry_quotes.short_put.strike, 'P'))
        short_call = option_map.get((entry_quotes.short_call.strike, 'C'))
        long_call = option_map.get((entry_quotes.long_call.strike, 'C'))

        if not all([long_put, short_put, short_call, long_call]):
            return None

        return IronCondorQuotes(
            symbol=symbol,
            trade_date=exit_date,
            expiry=expiry,
            spot_price=chain.spot_price,
            long_put=long_put,
            short_put=short_put,
            short_call=short_call,
            long_call=long_call,
        )

    def calculate_entry_credit(
        self,
        entry_quotes: Any,
        realistic: bool = True,
    ) -> float:
        """Calculate entry credit from quotes.

        Args:
            entry_quotes: IronCondorQuotes at entry
            realistic: If True, use bid for selling, ask for buying

        Returns:
            Net credit received in dollars.
        """
        if realistic:
            return entry_quotes.entry_credit_realistic() or 0.0
        return entry_quotes.net_credit or 0.0

    def calculate_exit_pnl(
        self,
        entry_quotes: Any,
        exit_quotes: Any,
        realistic: bool = True,
    ) -> PnLEstimate:
        """Calculate P&L using real entry and exit prices.

        Args:
            entry_quotes: IronCondorQuotes at entry
            exit_quotes: IronCondorQuotes at exit
            realistic: If True, apply realistic slippage

        Returns:
            PnLEstimate with actual P&L.
        """
        # Entry credit
        if realistic:
            entry_credit = entry_quotes.entry_credit_realistic() or 0.0
        else:
            entry_credit = entry_quotes.net_credit or 0.0

        # Exit debit
        if realistic:
            exit_debit = entry_quotes.exit_debit_realistic(exit_quotes) or 0.0
        else:
            exit_debit = exit_quotes.net_credit or 0.0

        # P&L = credit received - debit to close
        total_pnl = entry_credit - exit_debit

        # Transaction costs (4 legs in, 4 legs out)
        num_contracts = 1
        costs = self._calculate_costs(num_contracts * 8)  # 8 transactions total
        total_pnl -= costs

        # Max risk from entry quotes
        max_risk = entry_quotes.max_risk or 200.0
        pnl_pct = (total_pnl / max_risk * 100) if max_risk > 0 else 0

        return PnLEstimate(
            total_pnl=round(total_pnl, 2),
            vega_pnl=0.0,  # Not tracked with real prices
            theta_pnl=0.0,  # Not tracked with real prices
            costs=round(costs, 2),
            pnl_pct=round(pnl_pct, 2),
        )

    def estimate_current_pnl(
        self,
        entry_quotes: Any,
        current_quotes: Any,
        realistic: bool = True,
    ) -> PnLEstimate:
        """Estimate current P&L (mark-to-market).

        Uses mid prices for current value estimation.

        Args:
            entry_quotes: IronCondorQuotes at entry
            current_quotes: IronCondorQuotes at current date
            realistic: If True, entry uses realistic slippage

        Returns:
            PnLEstimate with current P&L.
        """
        # Entry credit (what we received)
        if realistic:
            entry_credit = entry_quotes.entry_credit_realistic() or 0.0
        else:
            entry_credit = entry_quotes.net_credit or 0.0

        # Current value (what it would cost to close at mid)
        current_value = current_quotes.net_credit or 0.0

        # P&L = entry credit - current value to close
        total_pnl = entry_credit - current_value

        # No costs yet (haven't exited)
        max_risk = entry_quotes.max_risk or 200.0
        pnl_pct = (total_pnl / max_risk * 100) if max_risk > 0 else 0

        return PnLEstimate(
            total_pnl=round(total_pnl, 2),
            vega_pnl=0.0,
            theta_pnl=0.0,
            costs=0.0,
            pnl_pct=round(pnl_pct, 2),
        )

    def _calculate_costs(self, num_legs: int) -> float:
        """Calculate transaction costs."""
        commission = num_legs * self.costs_config.commission_per_contract
        return commission


class CalendarSpreadPnLModel:
    """P&L estimation model for Calendar Spread positions.

    Calendar Spread characteristics (ATM call calendar):
    - Long vega (profits when IV increases)
    - Net theta positive near ATM (near leg decays faster than far leg)
    - Limited max loss (debit paid)
    - Limited max profit (hard to estimate, depends on IV and spot at near expiry)

    TOMIC Philosophy for Calendars:
    - These are VOLATILITY MISPRICING trades, NOT theta trades
    - Entry when IV is LOW (IV percentile <= 40%)
    - Entry when term structure shows front-month IV >= back-month (contango)
    - Exit quickly (5-10 days max) when mispricing corrects
    - Profit target: 5-10% of debit
    - Stop loss: 10% of debit

    Model approach:
    Since we don't have Greeks, we model P&L as a function of:
    1. IV change since entry (vega component - calendars are vega LONG)
    2. Term structure normalization
    3. Time value differential decay
    """

    # Model parameters calibrated for calendar spreads
    # Calendar is vega long, so profits when IV rises
    VEGA_SENSITIVITY = 2.0  # $ per vol point per $100 debit (higher than IC because net long vega)
    THETA_DECAY_DIFFERENTIAL = 0.15  # Fraction of debit captured from theta differential per 45 days

    def __init__(self, config: "BacktestConfig"):
        self.config = config
        self.costs_config = config.costs

    def estimate_debit(
        self,
        iv_at_entry: float,
        spot_price: float,
        near_dte: int,
        far_dte: int,
    ) -> float:
        """Estimate debit paid for an ATM Call Calendar Spread.

        Calendar spread debit depends on:
        - Time value differential between near and far leg
        - IV level (higher IV = higher premiums = higher debit)
        - Strike distance from spot (ATM = max time value)

        Args:
            iv_at_entry: ATM IV at entry (as decimal, e.g., 0.20 for 20%)
            spot_price: Current spot price
            near_dte: Days to expiration for near (short) leg
            far_dte: Days to expiration for far (long) leg

        Returns:
            Estimated debit paid in dollars per contract.
        """
        # Normalize IV
        # Use threshold of 2 to handle high-IV stocks (IV > 200% is unrealistic)
        iv_normalized = iv_at_entry if iv_at_entry <= 2 else iv_at_entry / 100

        # ATM call time value approximation (simplified Black-Scholes)
        # Time value ≈ 0.4 * spot * iv * sqrt(dte/365)
        near_time_value = 0.4 * spot_price * iv_normalized * (near_dte / 365) ** 0.5
        far_time_value = 0.4 * spot_price * iv_normalized * (far_dte / 365) ** 0.5

        # Calendar debit = far leg premium - near leg premium
        # We're buying the far leg and selling the near leg
        debit = far_time_value - near_time_value

        # Apply typical market conditions (bid-ask spread impact)
        # Calendar spreads typically cost 60-80% of theoretical due to spread
        debit = debit * 0.70

        # Contract multiplier
        debit_per_contract = debit * 100

        # Minimum debit floor (calendars always cost something)
        return max(debit_per_contract, 50.0)

    def estimate_pnl(
        self,
        iv_at_entry: float,
        iv_current: float,
        term_at_entry: Optional[float],
        term_current: Optional[float],
        days_in_trade: int,
        near_dte_at_entry: int,
        entry_debit: float,
    ) -> PnLEstimate:
        """Estimate current P&L for an open Calendar Spread position.

        Calendar P&L drivers:
        1. Vega P&L: Calendars are vega LONG - profit when IV rises
        2. Theta differential: Near leg decays faster than far leg
        3. Term structure normalization: If term structure normalizes, position profits

        Args:
            iv_at_entry: ATM IV at entry
            iv_current: Current ATM IV
            term_at_entry: Term structure (M1-M2) at entry (positive = front > back)
            term_current: Current term structure
            days_in_trade: Days since entry
            near_dte_at_entry: DTE of near leg at entry
            entry_debit: Debit paid at entry

        Returns:
            PnLEstimate with breakdown of P&L components.
        """
        # Normalize IV values
        # Use threshold of 2 instead of 1 to handle high-IV stocks correctly
        # IV > 200% (2.0 as decimal) is unrealistic, so IV > 2 means it's a percentage
        # This fixes the bug where IV=1.00 (100%) was incorrectly divided by 100
        iv_entry_norm = iv_at_entry if iv_at_entry <= 2 else iv_at_entry / 100
        iv_current_norm = iv_current if iv_current <= 2 else iv_current / 100

        # Calculate IV change in vol points
        iv_change = (iv_current_norm - iv_entry_norm) * 100  # In vol points

        # Vega P&L: Calendar is LONG vega, profits when IV rises
        # Scale by debit (larger position = more vega exposure)
        vega_pnl = iv_change * self.VEGA_SENSITIVITY * (entry_debit / 100)

        # Theta differential P&L
        # Near leg decays faster than far leg = net positive theta near ATM
        # But this effect diminishes as near leg approaches expiry
        time_fraction = days_in_trade / near_dte_at_entry if near_dte_at_entry > 0 else 0
        theta_progress = min(1.0, time_fraction ** 0.7)
        theta_pnl = entry_debit * theta_progress * self.THETA_DECAY_DIFFERENTIAL

        # Term structure normalization P&L
        # If term structure was inverted (front > back) and normalizes, we profit
        term_pnl = 0.0
        if term_at_entry is not None and term_current is not None:
            # term_m1_m2: positive means front-month IV > back-month IV
            # Calendar profits when this spread narrows (front IV drops relative to back)
            term_change = term_at_entry - term_current  # Positive if spread narrowed
            term_pnl = term_change * (entry_debit / 100) * 0.5  # 50 cents per point per $100

        # Calculate costs
        costs = self._calculate_costs(2)  # 2 legs for calendar

        # Total P&L
        total_pnl = vega_pnl + theta_pnl + term_pnl - costs

        # Cap at reasonable bounds
        # Max profit for calendar is typically 50-100% of debit
        max_profit = entry_debit * 1.0
        total_pnl = min(max_profit, total_pnl)

        # Max loss is the debit paid
        total_pnl = max(-entry_debit, total_pnl)

        pnl_pct = (total_pnl / entry_debit * 100) if entry_debit > 0 else 0

        return PnLEstimate(
            total_pnl=round(total_pnl, 2),
            vega_pnl=round(vega_pnl, 2),
            theta_pnl=round(theta_pnl + term_pnl, 2),  # Combine theta and term structure
            costs=round(costs, 2),
            pnl_pct=round(pnl_pct, 2),
        )

    def estimate_exit_pnl(
        self,
        iv_at_entry: float,
        iv_at_exit: float,
        term_at_entry: Optional[float],
        term_at_exit: Optional[float],
        days_in_trade: int,
        near_dte_at_entry: int,
        entry_debit: float,
        exit_reason: str,
    ) -> float:
        """Estimate final P&L at exit for calendar spread.

        Args:
            iv_at_entry: ATM IV at entry
            iv_at_exit: ATM IV at exit
            term_at_entry: Term structure at entry
            term_at_exit: Term structure at exit
            days_in_trade: Days in trade
            near_dte_at_entry: Near leg DTE at entry
            entry_debit: Debit paid
            exit_reason: Reason for exit

        Returns:
            Final P&L in dollars.
        """
        pnl_estimate = self.estimate_pnl(
            iv_at_entry=iv_at_entry,
            iv_current=iv_at_exit,
            term_at_entry=term_at_entry,
            term_current=term_at_exit,
            days_in_trade=days_in_trade,
            near_dte_at_entry=near_dte_at_entry,
            entry_debit=entry_debit,
        )

        # Apply exit-specific adjustments
        if exit_reason == "profit_target":
            # Cap at profit target (5-10% of debit)
            # Use configured profit target
            target_pct = getattr(self.config.exit_rules, 'profit_target_pct', 10.0)
            target_profit = entry_debit * (target_pct / 100)
            return min(pnl_estimate.total_pnl, target_profit)

        elif exit_reason == "stop_loss":
            # Apply stop loss (10% of debit for calendars)
            stop_pct = getattr(self.config.exit_rules, 'stop_loss_pct', 10.0)
            stop_loss = entry_debit * (stop_pct / 100)
            return max(pnl_estimate.total_pnl, -stop_loss)

        elif exit_reason == "near_leg_dte":
            # Exiting before near leg expiration
            # Use current P&L estimate
            return pnl_estimate.total_pnl

        elif exit_reason == "max_days_in_trade":
            # Time limit hit - use current estimate
            # For calendars, this often means the move didn't happen
            return pnl_estimate.total_pnl

        else:
            # Other exits: use estimate
            return pnl_estimate.total_pnl

    def _calculate_costs(self, num_legs: int) -> float:
        """Calculate transaction costs for a trade.

        Args:
            num_legs: Number of option legs in the trade

        Returns:
            Total costs in dollars.
        """
        commission = num_legs * self.costs_config.commission_per_contract
        return commission


__all__ = [
    "IronCondorPnLModel",
    "SimplePnLModel",
    "PnLEstimate",
    "GreeksBasedPnLModel",
    "GreeksSnapshot",
    "RealPricesPnLModel",
    "CalendarSpreadPnLModel",
]
