"""Exit evaluator implementing the 6 TOMIC/Dennis Chen exit rules.

Exit triggers (in order of priority):
1. Profit target: 50% of credit received
2. Stop loss: 100-150% of credit
3. Time decay: 5 DTE for expiry (avoid gamma risk)
4. Delta breach: Position delta > 20 (proxy: large IV spike)
5. IV collapse: IV drops 10+ vol points below entry
6. Max DIT: 45 days (Dennis Chen max holding period)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional, Tuple

from tomic.backtest.config import BacktestConfig, ExitRulesConfig
from tomic.backtest.pnl_model import IronCondorPnLModel, CalendarSpreadPnLModel, PnLEstimate
from tomic.backtest.results import ExitReason, IVDataPoint, SimulatedTrade


@dataclass
class ExitEvaluation:
    """Result of evaluating exit conditions for a trade."""

    should_exit: bool
    exit_reason: Optional[ExitReason] = None
    exit_pnl: float = 0.0
    message: str = ""


class ExitEvaluator:
    """Evaluates exit conditions for open trades.

    Implements the TOMIC/Dennis Chen exit discipline:
    - Take profits at 50% of credit (don't get greedy)
    - Cut losses at 100% of credit (risk management)
    - Exit at 5 DTE (avoid gamma risk near expiry)
    - Exit on delta breach (position going against us)
    - Exit on IV collapse (trade thesis realized)
    - Exit after 45 days (time limit discipline)

    Note: Delta breach is approximated since we don't have Greeks.
    We use a large IV spike (>15 vol points) as a proxy, since
    large IV moves typically correlate with large spot moves
    that would breach delta thresholds.
    """

    # Proxy threshold for delta breach (IV spike in vol points)
    # Lowered from 15.0 to 8.0 for more conservative/realistic breach detection
    IV_SPIKE_DELTA_PROXY = 8.0

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.exit_rules = config.exit_rules
        self.pnl_model = IronCondorPnLModel(config)

    def evaluate(
        self,
        trade: SimulatedTrade,
        current_date: date,
        current_iv: Optional[float],
        current_spot: Optional[float] = None,
    ) -> ExitEvaluation:
        """Evaluate all exit conditions for a trade.

        Conditions are checked in priority order. First trigger wins.

        Args:
            trade: The SimulatedTrade to evaluate
            current_date: Current simulation date
            current_iv: Current ATM IV for the symbol
            current_spot: Current spot price (for delta breach detection)

        Returns:
            ExitEvaluation with decision and details.
        """
        # Update days in trade
        days_in_trade = (current_date - trade.entry_date).days

        # Get current P&L estimate
        if current_iv is not None:
            pnl_estimate = self.pnl_model.estimate_pnl(
                iv_at_entry=trade.iv_at_entry,
                iv_current=current_iv,
                days_in_trade=days_in_trade,
                target_dte=self.config.target_dte,
                estimated_credit=trade.estimated_credit,
                max_risk=trade.max_risk,
            )
        else:
            # No IV data - can only check time-based exits
            pnl_estimate = PnLEstimate(
                total_pnl=0, vega_pnl=0, theta_pnl=0, costs=0, pnl_pct=0
            )

        # Calculate remaining DTE
        remaining_dte = (trade.target_expiry - current_date).days

        # Check exit conditions in priority order
        checks = [
            self._check_profit_target(trade, pnl_estimate),
            self._check_stop_loss(trade, pnl_estimate),
            self._check_time_decay(remaining_dte),
            self._check_delta_breach(trade, current_iv, current_spot),
            self._check_iv_collapse(trade, current_iv),
            self._check_max_dit(days_in_trade),
            self._check_expiration(remaining_dte),
        ]

        # Return first triggered exit condition
        for evaluation in checks:
            if evaluation.should_exit:
                # Calculate final P&L for this exit reason
                if current_iv is not None:
                    evaluation.exit_pnl = self.pnl_model.estimate_exit_pnl(
                        iv_at_entry=trade.iv_at_entry,
                        iv_at_exit=current_iv,
                        days_in_trade=days_in_trade,
                        target_dte=self.config.target_dte,
                        estimated_credit=trade.estimated_credit,
                        max_risk=trade.max_risk,
                        exit_reason=evaluation.exit_reason.value,
                        spot_at_entry=trade.spot_at_entry,
                        spot_at_exit=current_spot,
                    )
                return evaluation

        # No exit triggered
        return ExitEvaluation(should_exit=False)

    def _check_profit_target(
        self, trade: SimulatedTrade, pnl: PnLEstimate
    ) -> ExitEvaluation:
        """Check if profit target is reached (50% of credit)."""
        target_profit = trade.estimated_credit * (self.exit_rules.profit_target_pct / 100)

        if pnl.total_pnl >= target_profit:
            return ExitEvaluation(
                should_exit=True,
                exit_reason=ExitReason.PROFIT_TARGET,
                exit_pnl=target_profit,
                message=f"Profit target reached: ${pnl.total_pnl:.2f} >= ${target_profit:.2f}",
            )
        return ExitEvaluation(should_exit=False)

    def _check_stop_loss(
        self, trade: SimulatedTrade, pnl: PnLEstimate
    ) -> ExitEvaluation:
        """Check if stop loss is triggered (100% of credit)."""
        stop_loss = trade.estimated_credit * (self.exit_rules.stop_loss_pct / 100)

        if pnl.total_pnl <= -stop_loss:
            return ExitEvaluation(
                should_exit=True,
                exit_reason=ExitReason.STOP_LOSS,
                exit_pnl=-stop_loss,
                message=f"Stop loss triggered: ${pnl.total_pnl:.2f} <= -${stop_loss:.2f}",
            )
        return ExitEvaluation(should_exit=False)

    def _check_time_decay(self, remaining_dte: int) -> ExitEvaluation:
        """Check if position should exit due to DTE (avoid gamma risk)."""
        if remaining_dte <= self.exit_rules.min_dte:
            return ExitEvaluation(
                should_exit=True,
                exit_reason=ExitReason.TIME_DECAY,
                message=f"Time decay exit: {remaining_dte} DTE <= {self.exit_rules.min_dte} DTE minimum",
            )
        return ExitEvaluation(should_exit=False)

    # Spot move thresholds for delta breach (percentage move from entry)
    # For iron condors, short strikes are typically at 1-1.5 stddev
    # A move of ~1 stddev puts us near short strike = delta breach territory
    SPOT_MOVE_DELTA_BREACH = 5.0  # 5% spot move triggers delta breach

    def _check_delta_breach(
        self,
        trade: SimulatedTrade,
        current_iv: Optional[float],
        current_spot: Optional[float] = None,
    ) -> ExitEvaluation:
        """Check for delta breach using spot movement and IV spike.

        Delta breach detection now uses two methods:
        1. Actual spot movement: If spot moves > 5% from entry, short strikes
           are likely being tested (for 1.5 stddev wings at 30% IV)
        2. IV spike proxy: Large IV spikes correlate with large spot moves

        Both conditions are checked; either can trigger a breach.
        """
        # Method 1: Check actual spot movement (preferred if available)
        if current_spot is not None and trade.spot_at_entry is not None:
            spot_at_entry = trade.spot_at_entry
            if spot_at_entry > 0:
                spot_change_pct = abs((current_spot - spot_at_entry) / spot_at_entry) * 100

                # Scale threshold by IV at entry - higher IV = wider strikes = more tolerance
                iv_at_entry = trade.iv_at_entry if trade.iv_at_entry < 1 else trade.iv_at_entry / 100
                # At 20% IV, threshold is 5%. At 40% IV, threshold is 10%
                adjusted_threshold = self.SPOT_MOVE_DELTA_BREACH * (iv_at_entry / 0.20)
                adjusted_threshold = max(3.0, min(15.0, adjusted_threshold))  # Clamp 3-15%

                if spot_change_pct >= adjusted_threshold:
                    direction = "up" if current_spot > spot_at_entry else "down"
                    return ExitEvaluation(
                        should_exit=True,
                        exit_reason=ExitReason.DELTA_BREACH,
                        message=f"Delta breach: spot {direction} {spot_change_pct:.1f}% (threshold: {adjusted_threshold:.1f}%)",
                    )

        # Method 2: IV spike proxy (fallback or additional check)
        if current_iv is not None:
            # Normalize IV values
            iv_entry = trade.iv_at_entry if trade.iv_at_entry < 1 else trade.iv_at_entry / 100
            iv_current = current_iv if current_iv < 1 else current_iv / 100

            # Calculate IV change in vol points
            iv_change = (iv_current - iv_entry) * 100

            # Large IV spike suggests large spot move -> delta breach
            if iv_change >= self.IV_SPIKE_DELTA_PROXY:
                return ExitEvaluation(
                    should_exit=True,
                    exit_reason=ExitReason.DELTA_BREACH,
                    message=f"Delta breach (IV spike): IV up {iv_change:.1f} vol points",
                )

        return ExitEvaluation(should_exit=False)

    def _check_iv_collapse(
        self, trade: SimulatedTrade, current_iv: Optional[float]
    ) -> ExitEvaluation:
        """Check if IV has collapsed below entry - 10 vol points.

        IV collapse means our thesis played out (IV reverted).
        Take profits even if profit target not quite reached.
        """
        if current_iv is None:
            return ExitEvaluation(should_exit=False)

        # Normalize IV values
        iv_entry = trade.iv_at_entry if trade.iv_at_entry < 1 else trade.iv_at_entry / 100
        iv_current = current_iv if current_iv < 1 else current_iv / 100

        # Calculate IV drop in vol points
        iv_drop = (iv_entry - iv_current) * 100

        if iv_drop >= self.exit_rules.iv_collapse_threshold:
            return ExitEvaluation(
                should_exit=True,
                exit_reason=ExitReason.IV_COLLAPSE,
                message=f"IV collapse: IV down {iv_drop:.1f} vol points (threshold: {self.exit_rules.iv_collapse_threshold})",
            )
        return ExitEvaluation(should_exit=False)

    def _check_max_dit(self, days_in_trade: int) -> ExitEvaluation:
        """Check if maximum days in trade exceeded."""
        if days_in_trade >= self.exit_rules.max_days_in_trade:
            return ExitEvaluation(
                should_exit=True,
                exit_reason=ExitReason.MAX_DIT,
                message=f"Max DIT reached: {days_in_trade} days >= {self.exit_rules.max_days_in_trade} max",
            )
        return ExitEvaluation(should_exit=False)

    def _check_expiration(self, remaining_dte: int) -> ExitEvaluation:
        """Check if option is expiring (failsafe)."""
        if remaining_dte <= 0:
            return ExitEvaluation(
                should_exit=True,
                exit_reason=ExitReason.EXPIRATION,
                message="Position expired",
            )
        return ExitEvaluation(should_exit=False)


class CalendarExitEvaluator:
    """Evaluates exit conditions for Calendar Spread trades.

    TOMIC Calendar Exit Rules (in priority order):
    1. Profit target: 5-10% of debit (take profits quickly)
    2. Stop loss: 10% of debit (cut losses fast)
    3. Near-leg DTE: Exit 7-10 days before near-leg expiration
    4. Max DIT: 5-10 days (volatility mispricing trades should work fast)

    Key Philosophy:
    - Calendars are VOLATILITY MISPRICING trades, NOT theta trades
    - If the move doesn't come in 5-10 days, exit
    - Don't hold for theta decay - that's not the thesis
    """

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.exit_rules = config.exit_rules
        self.pnl_model = CalendarSpreadPnLModel(config)

    def evaluate(
        self,
        trade: SimulatedTrade,
        current_date: date,
        current_iv: Optional[float],
        current_term: Optional[float] = None,
        term_at_entry: Optional[float] = None,
    ) -> ExitEvaluation:
        """Evaluate all exit conditions for a calendar trade.

        Args:
            trade: The SimulatedTrade to evaluate
            current_date: Current simulation date
            current_iv: Current ATM IV for the symbol
            current_term: Current term structure (M1-M2)
            term_at_entry: Term structure at entry

        Returns:
            ExitEvaluation with decision and details.
        """
        # Update days in trade
        days_in_trade = (current_date - trade.entry_date).days

        # Get entry debit (max_risk for calendars = debit paid)
        entry_debit = trade.entry_debit if trade.entry_debit else trade.max_risk

        # Calculate near leg DTE at entry
        near_dte_at_entry = (trade.short_expiry - trade.entry_date).days if trade.short_expiry else 45

        # Get current P&L estimate
        if current_iv is not None and entry_debit > 0:
            pnl_estimate = self.pnl_model.estimate_pnl(
                iv_at_entry=trade.iv_at_entry,
                iv_current=current_iv,
                term_at_entry=term_at_entry,
                term_current=current_term,
                days_in_trade=days_in_trade,
                near_dte_at_entry=near_dte_at_entry,
                entry_debit=entry_debit,
            )
        else:
            pnl_estimate = PnLEstimate(
                total_pnl=0, vega_pnl=0, theta_pnl=0, costs=0, pnl_pct=0
            )

        # Calculate remaining DTE for near leg
        if trade.short_expiry:
            near_leg_dte = (trade.short_expiry - current_date).days
        else:
            near_leg_dte = (trade.target_expiry - current_date).days

        # Check exit conditions in priority order
        checks = [
            self._check_profit_target(entry_debit, pnl_estimate),
            self._check_stop_loss(entry_debit, pnl_estimate),
            self._check_near_leg_dte(near_leg_dte),
            self._check_max_dit(days_in_trade),
        ]

        # Return first triggered exit condition
        for evaluation in checks:
            if evaluation.should_exit:
                # Calculate final P&L for this exit reason
                if current_iv is not None:
                    evaluation.exit_pnl = self.pnl_model.estimate_exit_pnl(
                        iv_at_entry=trade.iv_at_entry,
                        iv_at_exit=current_iv,
                        term_at_entry=term_at_entry,
                        term_at_exit=current_term,
                        days_in_trade=days_in_trade,
                        near_dte_at_entry=near_dte_at_entry,
                        entry_debit=entry_debit,
                        exit_reason=evaluation.exit_reason.value,
                    )
                return evaluation

        # No exit triggered
        return ExitEvaluation(should_exit=False)

    def _check_profit_target(
        self, entry_debit: float, pnl: PnLEstimate
    ) -> ExitEvaluation:
        """Check if profit target is reached (5-10% of debit for calendars)."""
        # Calendar profit target is much lower than iron condor
        target_pct = self.exit_rules.profit_target_pct  # Should be 5-10 for calendars
        target_profit = entry_debit * (target_pct / 100)

        if pnl.total_pnl >= target_profit:
            return ExitEvaluation(
                should_exit=True,
                exit_reason=ExitReason.PROFIT_TARGET,
                exit_pnl=target_profit,
                message=f"Profit target reached: ${pnl.total_pnl:.2f} >= ${target_profit:.2f} ({target_pct}% of debit)",
            )
        return ExitEvaluation(should_exit=False)

    def _check_stop_loss(
        self, entry_debit: float, pnl: PnLEstimate
    ) -> ExitEvaluation:
        """Check if stop loss is triggered (10% of debit for calendars)."""
        stop_pct = self.exit_rules.stop_loss_pct  # Should be 10 for calendars
        stop_loss = entry_debit * (stop_pct / 100)

        if pnl.total_pnl <= -stop_loss:
            return ExitEvaluation(
                should_exit=True,
                exit_reason=ExitReason.STOP_LOSS,
                exit_pnl=-stop_loss,
                message=f"Stop loss triggered: ${pnl.total_pnl:.2f} <= -${stop_loss:.2f} ({stop_pct}% of debit)",
            )
        return ExitEvaluation(should_exit=False)

    def _check_near_leg_dte(self, near_leg_dte: int) -> ExitEvaluation:
        """Check if near leg is approaching expiration (7-10 days)."""
        # Use min_dte from config (should be 7-10 for calendars)
        min_dte = self.exit_rules.min_dte

        if near_leg_dte <= min_dte:
            return ExitEvaluation(
                should_exit=True,
                exit_reason=ExitReason.NEAR_LEG_DTE,
                message=f"Near-leg DTE exit: {near_leg_dte} DTE <= {min_dte} DTE minimum",
            )
        return ExitEvaluation(should_exit=False)

    def _check_max_dit(self, days_in_trade: int) -> ExitEvaluation:
        """Check if maximum days in trade exceeded (5-10 days for calendars)."""
        max_dit = self.exit_rules.max_days_in_trade  # Should be 5-10 for calendars

        if days_in_trade >= max_dit:
            return ExitEvaluation(
                should_exit=True,
                exit_reason=ExitReason.MAX_DIT,
                message=f"Max DIT reached: {days_in_trade} days >= {max_dit} max (move didn't come)",
            )
        return ExitEvaluation(should_exit=False)


__all__ = ["ExitEvaluator", "ExitEvaluation", "CalendarExitEvaluator"]
