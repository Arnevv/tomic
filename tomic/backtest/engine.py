"""Backtest engine - main orchestrator for running backtests.

Coordinates all components:
1. Load historical IV data
2. Split into in-sample / out-of-sample
3. Generate entry signals
4. Simulate trades with exit rules
5. Calculate performance metrics
6. Compare in-sample vs out-of-sample
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional

from tomic.backtest.config import BacktestConfig, load_backtest_config
from tomic.backtest.data_loader import DataLoader, IVTimeSeries
from tomic.backtest.metrics import MetricsCalculator, calculate_degradation_score
from tomic.backtest.results import (
    BacktestResult,
    ExitReason,
    PerformanceMetrics,
    SimulatedTrade,
    TradeStatus,
)
from tomic.backtest.signal_generator import SignalGenerator, SignalFilter
from tomic.backtest.trade_simulator import TradeSimulator
from tomic.logutils import logger


class BacktestEngine:
    """Main backtest orchestrator.

    Runs the complete backtest workflow:
    1. Load configuration
    2. Load and validate historical data
    3. Split data chronologically (30% in-sample, 70% out-of-sample)
    4. Run simulation on each period
    5. Calculate and compare metrics
    6. Generate results report

    Usage:
        engine = BacktestEngine()
        result = engine.run()
        print(result.summary())
    """

    def __init__(
        self,
        config: Optional[BacktestConfig] = None,
        progress_callback: Optional[Callable[[str, float], None]] = None,
    ):
        """Initialize the backtest engine.

        Args:
            config: BacktestConfig instance. If None, loads from default location.
            progress_callback: Optional callback for progress updates (message, percent)
        """
        self.config = config or load_backtest_config()
        self.progress_callback = progress_callback

        # Initialize components
        self.data_loader = DataLoader(self.config)
        self.signal_generator = SignalGenerator(self.config)
        self.metrics_calculator = MetricsCalculator()

    def run(self) -> BacktestResult:
        """Run the complete backtest.

        Returns:
            BacktestResult with all trades and metrics.
        """
        self._report_progress("Initializing backtest...", 0)

        result = BacktestResult()
        result.config_summary = self._get_config_summary()
        result.start_date = date.fromisoformat(self.config.start_date)
        result.end_date = date.fromisoformat(self.config.end_date)
        result.in_sample_end_date = self.config.get_in_sample_end_date()

        # Step 1: Load data
        self._report_progress("Loading historical IV data...", 5)
        iv_data = self.data_loader.load_all()

        if not iv_data:
            result.is_valid = False
            result.validation_messages.append("No IV data loaded for any symbol")
            logger.error("No IV data available - cannot run backtest")
            return result

        data_summary = self.data_loader.get_data_summary()
        logger.info(
            f"Loaded data for {data_summary['symbols_loaded']} symbols, "
            f"{data_summary['total_data_points']} total data points"
        )

        # Step 2: Split data
        self._report_progress("Splitting data into in-sample / out-of-sample...", 10)
        split_date = self.config.get_in_sample_end_date()
        in_sample_data, out_sample_data = self.data_loader.split_by_date(split_date)

        logger.info(
            f"Split at {split_date}: "
            f"in-sample={sum(len(ts) for ts in in_sample_data.values())} points, "
            f"out-of-sample={sum(len(ts) for ts in out_sample_data.values())} points"
        )

        # Step 3: Run in-sample simulation
        self._report_progress("Running in-sample simulation...", 15)
        in_sample_trades = self._run_simulation(
            iv_data=in_sample_data,
            start_date=result.start_date,
            end_date=split_date,
            period_name="in-sample",
            progress_start=15,
            progress_end=45,
        )

        # Step 4: Run out-of-sample simulation
        self._report_progress("Running out-of-sample simulation...", 50)
        out_sample_start = self.config.get_out_sample_start_date()
        out_sample_trades = self._run_simulation(
            iv_data=out_sample_data,
            start_date=out_sample_start,
            end_date=result.end_date,
            period_name="out-of-sample",
            progress_start=50,
            progress_end=80,
        )

        # Combine all trades
        result.trades = in_sample_trades + out_sample_trades

        # Step 5: Calculate metrics
        self._report_progress("Calculating performance metrics...", 85)

        result.in_sample_metrics = self.metrics_calculator.calculate(in_sample_trades)
        result.out_sample_metrics = self.metrics_calculator.calculate(out_sample_trades)
        result.combined_metrics = self.metrics_calculator.calculate(result.trades)

        # Step 6: Calculate degradation
        self._report_progress("Analyzing in-sample vs out-of-sample...", 90)

        if result.in_sample_metrics and result.out_sample_metrics:
            result.degradation_score = calculate_degradation_score(
                result.in_sample_metrics,
                result.out_sample_metrics,
            )

        # Step 7: Build equity curve
        self._report_progress("Building equity curve...", 95)
        result.equity_curve = self._build_equity_curve(result.trades)

        # Validation checks
        self._validate_result(result)

        self._report_progress("Backtest complete!", 100)

        # Log summary
        self._log_summary(result)

        return result

    def _run_simulation(
        self,
        iv_data: Dict[str, IVTimeSeries],
        start_date: date,
        end_date: date,
        period_name: str,
        progress_start: float,
        progress_end: float,
    ) -> List[SimulatedTrade]:
        """Run simulation for a specific period.

        Args:
            iv_data: IV time series data for the period
            start_date: Start date of simulation
            end_date: End date of simulation
            period_name: Name for logging (e.g., "in-sample")
            progress_start: Starting progress percentage
            progress_end: Ending progress percentage

        Returns:
            List of SimulatedTrade objects from this period.
        """
        simulator = TradeSimulator(self.config, use_greeks_model=self.config.use_greeks_model)

        # Get all trading dates in period
        all_dates = []
        for ts in iv_data.values():
            all_dates.extend(ts.dates())
        trading_dates = sorted(set(d for d in all_dates if start_date <= d <= end_date))

        if not trading_dates:
            logger.warning(f"No trading dates found for {period_name} period")
            return []

        total_days = len(trading_dates)
        logger.info(f"Simulating {period_name}: {total_days} trading days")

        # Simulate each day
        for i, current_date in enumerate(trading_dates):
            # Progress update
            if total_days > 0:
                progress = progress_start + (progress_end - progress_start) * (i / total_days)
                if i % 100 == 0:  # Update every 100 days
                    self._report_progress(
                        f"Simulating {period_name}: {current_date}", progress
                    )

            # Process existing positions (check exits)
            simulator.process_day(current_date, iv_data)

            # Check for new entry signals
            open_positions = simulator.get_open_position_symbols()
            signals = self.signal_generator.scan_for_signals(
                iv_data=iv_data,
                trading_date=current_date,
                open_positions=open_positions,
            )

            # Open new positions for valid signals
            for signal in signals:
                if simulator.can_open_position(signal.symbol):
                    simulator.open_trade(signal)

        # Force close any remaining positions at end of period
        if simulator.get_open_positions():
            simulator.force_close_all(end_date, ExitReason.MANUAL)

        trades = simulator.get_all_trades()
        summary = simulator.get_summary()

        logger.info(
            f"{period_name} complete: {summary['total_trades']} trades, "
            f"win rate {summary['win_rate']:.1%}, "
            f"total P&L ${summary['total_pnl']:.2f}"
        )

        return trades

    def _build_equity_curve(
        self, trades: List[SimulatedTrade]
    ) -> List[Dict[str, Any]]:
        """Build equity curve data from trades."""
        initial_capital = self.metrics_calculator.initial_capital

        # Sort trades by exit date
        sorted_trades = sorted(
            [t for t in trades if t.exit_date and t.status == TradeStatus.CLOSED],
            key=lambda t: t.exit_date,
        )

        equity_curve = []
        cumulative_pnl = 0.0

        for trade in sorted_trades:
            cumulative_pnl += trade.final_pnl
            equity = initial_capital + cumulative_pnl

            equity_curve.append({
                "date": str(trade.exit_date),
                "equity": round(equity, 2),
                "cumulative_pnl": round(cumulative_pnl, 2),
                "trade_pnl": round(trade.final_pnl, 2),
                "symbol": trade.symbol,
                "exit_reason": trade.exit_reason.value if trade.exit_reason else None,
            })

        return equity_curve

    def _validate_result(self, result: BacktestResult) -> None:
        """Run validation checks on the result."""
        messages = []

        # Check minimum trades
        if len(result.trades) < 30:
            messages.append(
                f"Warning: Only {len(result.trades)} trades - results may not be statistically significant"
            )

        # Check degradation
        if result.degradation_score > 50:
            messages.append(
                f"Warning: High degradation score ({result.degradation_score:.1f}%) - "
                "strategy may be overfit to in-sample data"
            )

        # Check if out-of-sample is profitable
        if result.out_sample_metrics:
            if result.out_sample_metrics.total_pnl < 0:
                messages.append(
                    "Warning: Out-of-sample period is unprofitable"
                )

        # Check win rate sanity
        if result.combined_metrics and result.combined_metrics.win_rate < 0.3:
            messages.append(
                f"Warning: Low win rate ({result.combined_metrics.win_rate:.1%}) - "
                "review entry criteria"
            )

        result.validation_messages = messages
        result.is_valid = len([m for m in messages if "Warning:" in m]) < 3

    def _get_config_summary(self) -> Dict[str, Any]:
        """Get summary of configuration for reporting."""
        return {
            "strategy_type": self.config.strategy_type,
            "symbols": self.config.symbols,
            "date_range": f"{self.config.start_date} to {self.config.end_date}",
            "target_dte": self.config.target_dte,
            "entry_rules": {
                "iv_percentile_min": self.config.entry_rules.iv_percentile_min,
                "iv_rank_min": self.config.entry_rules.iv_rank_min,
            },
            "exit_rules": {
                "profit_target_pct": self.config.exit_rules.profit_target_pct,
                "stop_loss_pct": self.config.exit_rules.stop_loss_pct,
                "min_dte": self.config.exit_rules.min_dte,
                "max_days_in_trade": self.config.exit_rules.max_days_in_trade,
            },
            "position_sizing": {
                "max_risk_per_trade": self.config.position_sizing.max_risk_per_trade,
            },
            "sample_split": {
                "in_sample_ratio": self.config.sample_split.in_sample_ratio,
            },
        }

    def _report_progress(self, message: str, percent: float) -> None:
        """Report progress via callback if available."""
        if self.progress_callback:
            self.progress_callback(message, percent)
        logger.debug(f"[{percent:.0f}%] {message}")

    def _log_summary(self, result: BacktestResult) -> None:
        """Log summary of backtest results."""
        logger.info("=" * 60)
        logger.info("BACKTEST SUMMARY")
        logger.info("=" * 60)

        if result.combined_metrics:
            m = result.combined_metrics
            logger.info(f"Total Trades: {m.total_trades}")
            logger.info(f"Win Rate: {m.win_rate:.1%}")
            logger.info(f"Total P&L: ${m.total_pnl:.2f}")
            logger.info(f"Sharpe Ratio: {m.sharpe_ratio:.2f}")
            logger.info(f"Max Drawdown: {m.max_drawdown_pct:.1f}%")
            logger.info("-" * 60)
            logger.info("ADDITIONAL METRICS:")
            logger.info(f"  Ret/DD: {m.ret_dd:.2f}")
            logger.info(f"  Profit Factor: {m.profit_factor:.2f}")
            logger.info(f"  Average Winner: ${m.average_winner:.2f}")
            logger.info(f"  Average Loser: ${m.average_loser:.2f}")
            logger.info(f"  Expectancy: ${m.expectancy:.2f}")
            logger.info(f"  SQN: {m.sqn:.2f}")

        if result.in_sample_metrics and result.out_sample_metrics:
            logger.info("-" * 60)
            logger.info("IN-SAMPLE vs OUT-OF-SAMPLE:")
            logger.info(
                f"  In-Sample Sharpe: {result.in_sample_metrics.sharpe_ratio:.2f}"
            )
            logger.info(
                f"  Out-Sample Sharpe: {result.out_sample_metrics.sharpe_ratio:.2f}"
            )
            logger.info(f"  Degradation Score: {result.degradation_score:.1f}%")

        if result.validation_messages:
            logger.info("-" * 60)
            for msg in result.validation_messages:
                logger.info(msg)

        logger.info("=" * 60)


def run_backtest(
    config: Optional[BacktestConfig] = None,
    progress_callback: Optional[Callable[[str, float], None]] = None,
) -> BacktestResult:
    """Convenience function to run a backtest.

    Args:
        config: Optional BacktestConfig. Uses default if not provided.
        progress_callback: Optional callback for progress updates.

    Returns:
        BacktestResult with all data.
    """
    engine = BacktestEngine(config=config, progress_callback=progress_callback)
    return engine.run()


__all__ = ["BacktestEngine", "run_backtest"]
