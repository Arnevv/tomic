"""Trade simulator for managing trade lifecycle in backtesting.

Handles:
- Opening new trades based on entry signals
- Tracking open positions
- Processing exits
- Managing position limits
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional

from tomic.backtest.config import BacktestConfig
from tomic.backtest.data_loader import IVTimeSeries
from tomic.backtest.exit_evaluator import ExitEvaluator, ExitEvaluation
from tomic.backtest.pnl_model import IronCondorPnLModel, GreeksBasedPnLModel
from tomic.backtest.results import (
    EntrySignal,
    ExitReason,
    SimulatedTrade,
    TradeStatus,
    IVDataPoint,
)
from tomic.logutils import logger


class TradeSimulator:
    """Simulates trade lifecycle from entry to exit.

    Manages:
    - Position tracking per symbol
    - Entry execution
    - Daily position updates
    - Exit execution

    Constraints:
    - Max 1 position per symbol at a time
    - Max total positions across all symbols
    - Fixed risk per trade ($200)
    - Minimum risk/reward ratio (from strategy config)
    """

    def __init__(
        self,
        config: BacktestConfig,
        use_greeks_model: bool = False,
        strategy_config: Optional[Dict[str, any]] = None,
    ):
        self.config = config
        self.pnl_model = IronCondorPnLModel(config)
        self.greeks_model = GreeksBasedPnLModel(config) if use_greeks_model else None
        self.use_greeks_model = use_greeks_model
        self.exit_evaluator = ExitEvaluator(config)

        # Strategy-specific config (min_risk_reward, min_rom, etc.)
        self.strategy_config = strategy_config or {}

        # Track open positions by symbol
        self._open_positions: Dict[str, SimulatedTrade] = {}

        # All trades (open and closed)
        self._all_trades: List[SimulatedTrade] = []

        # Track rejections for diagnostics
        self._rr_rejections: int = 0

    def get_open_positions(self) -> Dict[str, SimulatedTrade]:
        """Get currently open positions."""
        return self._open_positions.copy()

    def get_all_trades(self) -> List[SimulatedTrade]:
        """Get all trades (open and closed)."""
        return self._all_trades.copy()

    def has_position(self, symbol: str) -> bool:
        """Check if a position is open for a symbol."""
        return symbol in self._open_positions

    def get_open_position_symbols(self) -> Dict[str, bool]:
        """Get dict of symbols with open positions."""
        return {symbol: True for symbol in self._open_positions}

    def can_open_position(self, symbol: str) -> bool:
        """Check if a new position can be opened for a symbol."""
        # Check per-symbol limit
        if self.has_position(symbol):
            return False

        # Check total position limit
        max_positions = self.config.position_sizing.max_total_positions
        if len(self._open_positions) >= max_positions:
            return False

        return True

    def open_trade(self, signal: EntrySignal) -> Optional[SimulatedTrade]:
        """Open a new trade based on an entry signal.

        Args:
            signal: EntrySignal with entry details

        Returns:
            SimulatedTrade if opened successfully, None otherwise.
        """
        if not self.can_open_position(signal.symbol):
            logger.debug(f"Cannot open position for {signal.symbol} - limit reached")
            return None

        # Calculate position parameters
        max_risk = self.config.position_sizing.max_risk_per_trade
        target_dte = self.config.target_dte

        # Calculate target expiry date
        target_expiry = signal.date + timedelta(days=target_dte)

        # Get stddev_range from strategy config (affects credit calculation)
        stddev_range = self.strategy_config.get("stddev_range")

        # Estimate credit received
        if self.use_greeks_model and self.greeks_model and signal.spot_at_entry:
            estimated_credit = self.greeks_model.estimate_credit_from_greeks(
                spot_price=signal.spot_at_entry,
                atm_iv=signal.iv_at_entry,
                dte=target_dte,
                max_risk=max_risk,
                stddev_range=stddev_range,
            )
        else:
            estimated_credit = self.pnl_model.estimate_credit(
                iv_at_entry=signal.iv_at_entry,
                max_risk=max_risk,
                target_dte=target_dte,
                stddev_range=stddev_range,
            )

        # Apply slippage to credit
        slippage_pct = self.config.costs.slippage_pct / 100
        estimated_credit = estimated_credit * (1 - slippage_pct)

        # Check minimum risk/reward ratio from strategy config
        # R/R = max_loss / max_profit (TOMIC definition: risk per unit reward)
        # Lower is better. Threshold check: R/R <= min_rr
        min_rr = self.strategy_config.get("min_risk_reward")
        if min_rr is not None and estimated_credit > 0:
            # Calculate actual max_loss based on wing width
            wing_width = self.config.iron_condor_wing_width * 100  # Convert to dollars
            actual_max_loss = wing_width - estimated_credit
            actual_rr = actual_max_loss / estimated_credit
            if actual_rr > min_rr:
                logger.debug(
                    f"Rejected {signal.symbol} - R/R {actual_rr:.2f} > max {min_rr}"
                )
                self._rr_rejections += 1
                return None

        # Create trade
        trade = SimulatedTrade(
            entry_date=signal.date,
            symbol=signal.symbol,
            strategy_type=self.config.strategy_type,
            iv_at_entry=signal.iv_at_entry,
            iv_percentile_at_entry=signal.iv_percentile_at_entry,
            iv_rank_at_entry=signal.iv_rank_at_entry,
            spot_at_entry=signal.spot_at_entry,
            target_expiry=target_expiry,
            max_risk=max_risk,
            estimated_credit=estimated_credit,
            num_contracts=1,  # Simplified for MVP
            status=TradeStatus.OPEN,
        )

        # Calculate and store Greeks at entry (if using Greeks model)
        if self.use_greeks_model and self.greeks_model and signal.spot_at_entry:
            trade.greeks_at_entry = self.greeks_model.calculate_ic_greeks(
                spot_price=signal.spot_at_entry,
                atm_iv=signal.iv_at_entry,
                dte=target_dte,
            )

        # Track the trade
        self._open_positions[signal.symbol] = trade
        self._all_trades.append(trade)

        logger.debug(
            f"Opened {trade.strategy_type} on {signal.symbol} "
            f"@ IV {signal.iv_at_entry:.1%}, credit ${estimated_credit:.2f}"
        )

        return trade

    def process_day(
        self,
        current_date: date,
        iv_data: Dict[str, IVTimeSeries],
    ) -> List[SimulatedTrade]:
        """Process all open positions for a given day.

        Checks exit conditions and closes trades as needed.

        Args:
            current_date: Current simulation date
            iv_data: IV time series data for all symbols

        Returns:
            List of trades that were closed on this day.
        """
        closed_trades: List[SimulatedTrade] = []
        symbols_to_close: List[str] = []

        for symbol, trade in self._open_positions.items():
            # Get current IV for the symbol
            ts = iv_data.get(symbol)
            current_iv = None
            if ts:
                dp = ts.get(current_date)
                if dp:
                    current_iv = dp.atm_iv

            # Update days in trade
            trade.days_in_trade = (current_date - trade.entry_date).days

            # Update P&L tracking
            if current_iv is not None:
                trade.iv_history.append(current_iv)

                # Use Greeks-based P&L if available
                if self.use_greeks_model and self.greeks_model and trade.greeks_at_entry and trade.spot_at_entry and ts:
                    # Get current spot price
                    current_dp = ts.get(current_date)
                    current_spot = current_dp.spot_price if current_dp else trade.spot_at_entry
                    if current_spot:
                        trade.spot_history.append(current_spot)

                        # Calculate current Greeks
                        greeks_current = self.greeks_model.calculate_ic_greeks(
                            spot_price=current_spot,
                            atm_iv=current_iv,
                            dte=max(0, (trade.target_expiry - current_date).days),
                        )
                        trade.greeks_history.append(greeks_current)

                        # Calculate P&L from Greeks
                        pnl_estimate = self.greeks_model.estimate_pnl_from_greeks(
                            greeks_entry=trade.greeks_at_entry,
                            greeks_current=greeks_current,
                            days_in_trade=trade.days_in_trade,
                            estimated_credit=trade.estimated_credit,
                            max_risk=trade.max_risk,
                            spot_at_entry=trade.spot_at_entry,
                            spot_current=current_spot,
                        )
                    else:
                        # Fallback to standard model if no spot data
                        pnl_estimate = self.pnl_model.estimate_pnl(
                            iv_at_entry=trade.iv_at_entry,
                            iv_current=current_iv,
                            days_in_trade=trade.days_in_trade,
                            target_dte=self.config.target_dte,
                            estimated_credit=trade.estimated_credit,
                            max_risk=trade.max_risk,
                        )
                else:
                    # Use standard IV-based model
                    pnl_estimate = self.pnl_model.estimate_pnl(
                        iv_at_entry=trade.iv_at_entry,
                        iv_current=current_iv,
                        days_in_trade=trade.days_in_trade,
                        target_dte=self.config.target_dte,
                        estimated_credit=trade.estimated_credit,
                        max_risk=trade.max_risk,
                    )

                trade.current_pnl = pnl_estimate.total_pnl
                trade.pnl_history.append(pnl_estimate.total_pnl)

            # Evaluate exit conditions
            evaluation = self.exit_evaluator.evaluate(
                trade=trade,
                current_date=current_date,
                current_iv=current_iv,
            )

            if evaluation.should_exit:
                # Close the trade
                trade.close(
                    exit_date=current_date,
                    exit_reason=evaluation.exit_reason,
                    final_pnl=evaluation.exit_pnl,
                    iv_at_exit=current_iv,
                    spot_at_exit=None,  # We don't track spot in this simulation
                )
                symbols_to_close.append(symbol)
                closed_trades.append(trade)

                logger.debug(
                    f"Closed {trade.symbol} - {evaluation.exit_reason.value}: "
                    f"P&L ${evaluation.exit_pnl:.2f}, DIT {trade.days_in_trade}d"
                )

        # Remove closed positions from tracking
        for symbol in symbols_to_close:
            del self._open_positions[symbol]

        return closed_trades

    def force_close_all(
        self,
        current_date: date,
        reason: ExitReason = ExitReason.MANUAL,
    ) -> List[SimulatedTrade]:
        """Force close all open positions.

        Used at end of backtest period to close any remaining positions.

        Args:
            current_date: Date to use for closing
            reason: Exit reason to record

        Returns:
            List of closed trades.
        """
        closed_trades: List[SimulatedTrade] = []

        for symbol, trade in list(self._open_positions.items()):
            # Use last known P&L
            final_pnl = trade.current_pnl

            trade.close(
                exit_date=current_date,
                exit_reason=reason,
                final_pnl=final_pnl,
                iv_at_exit=trade.iv_history[-1] if trade.iv_history else None,
            )
            closed_trades.append(trade)

            logger.debug(
                f"Force closed {trade.symbol} - {reason.value}: "
                f"P&L ${final_pnl:.2f}"
            )

        self._open_positions.clear()
        return closed_trades

    def get_summary(self) -> Dict[str, any]:
        """Get summary statistics of the simulation."""
        all_trades = self._all_trades
        closed_trades = [t for t in all_trades if t.status == TradeStatus.CLOSED]
        open_trades = [t for t in all_trades if t.status == TradeStatus.OPEN]

        winners = [t for t in closed_trades if t.is_winner()]
        losers = [t for t in closed_trades if not t.is_winner()]

        total_pnl = sum(t.final_pnl for t in closed_trades)

        return {
            "total_trades": len(all_trades),
            "closed_trades": len(closed_trades),
            "open_trades": len(open_trades),
            "winners": len(winners),
            "losers": len(losers),
            "win_rate": len(winners) / len(closed_trades) if closed_trades else 0,
            "total_pnl": total_pnl,
            "avg_pnl": total_pnl / len(closed_trades) if closed_trades else 0,
            "rr_rejections": self._rr_rejections,
        }


__all__ = ["TradeSimulator"]
