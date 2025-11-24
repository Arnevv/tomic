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
from tomic.backtest.pnl_model import IronCondorPnLModel, PnLEstimate
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
    IV_SPIKE_DELTA_PROXY = 15.0

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.exit_rules = config.exit_rules
        self.pnl_model = IronCondorPnLModel(config)

    def evaluate(
        self,
        trade: SimulatedTrade,
        current_date: date,
        current_iv: Optional[float],
    ) -> ExitEvaluation:
        """Evaluate all exit conditions for a trade.

        Conditions are checked in priority order. First trigger wins.

        Args:
            trade: The SimulatedTrade to evaluate
            current_date: Current simulation date
            current_iv: Current ATM IV for the symbol

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
            self._check_delta_breach(trade, current_iv),
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

    def _check_delta_breach(
        self, trade: SimulatedTrade, current_iv: Optional[float]
    ) -> ExitEvaluation:
        """Check for delta breach (proxied by large IV spike).

        Since we don't have Greeks, we use a large IV spike as a proxy
        for delta breach. Large IV spikes typically correlate with
        large spot moves that would cause delta to exceed thresholds.
        """
        if current_iv is None:
            return ExitEvaluation(should_exit=False)

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
                message=f"Delta breach (IV spike proxy): IV up {iv_change:.1f} vol points",
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


__all__ = ["ExitEvaluator", "ExitEvaluation"]
