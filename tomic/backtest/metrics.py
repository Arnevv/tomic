"""Performance metrics calculation for backtesting.

Calculates comprehensive metrics including:
- Return metrics (total return, CAGR, Sharpe, Sortino)
- Risk metrics (max drawdown, volatility, Calmar)
- Trade metrics (win rate, profit factor, expectancy)
- Exit reason breakdown
- Per-symbol analysis
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from tomic.backtest.results import (
    ExitReason,
    PerformanceMetrics,
    SimulatedTrade,
    TradeStatus,
)


class MetricsCalculator:
    """Calculate performance metrics from backtest trades."""

    # Risk-free rate for Sharpe/Sortino calculations
    RISK_FREE_RATE = 0.04  # 4% annual

    def __init__(self, initial_capital: float = 10000.0):
        """Initialize with starting capital for return calculations.

        Args:
            initial_capital: Starting capital for percentage calculations.
        """
        self.initial_capital = initial_capital

    def calculate(self, trades: List[SimulatedTrade]) -> PerformanceMetrics:
        """Calculate all metrics from a list of trades.

        Args:
            trades: List of SimulatedTrade objects (should be closed)

        Returns:
            PerformanceMetrics with all calculated statistics.
        """
        closed_trades = [t for t in trades if t.status == TradeStatus.CLOSED]

        if not closed_trades:
            return PerformanceMetrics()

        metrics = PerformanceMetrics()

        # Basic counts
        metrics.total_trades = len(closed_trades)
        metrics.winning_trades = sum(1 for t in closed_trades if t.final_pnl > 0)
        metrics.losing_trades = sum(1 for t in closed_trades if t.final_pnl <= 0)
        metrics.win_rate = (
            metrics.winning_trades / metrics.total_trades
            if metrics.total_trades > 0
            else 0
        )

        # P&L metrics
        metrics.total_pnl = sum(t.final_pnl for t in closed_trades)
        metrics.gross_profit = sum(t.final_pnl for t in closed_trades if t.final_pnl > 0)
        metrics.gross_loss = abs(
            sum(t.final_pnl for t in closed_trades if t.final_pnl <= 0)
        )
        metrics.average_pnl = metrics.total_pnl / metrics.total_trades

        # Average winner/loser
        winners = [t for t in closed_trades if t.final_pnl > 0]
        losers = [t for t in closed_trades if t.final_pnl <= 0]

        metrics.average_winner = (
            sum(t.final_pnl for t in winners) / len(winners) if winners else 0
        )
        metrics.average_loser = (
            abs(sum(t.final_pnl for t in losers)) / len(losers) if losers else 0
        )

        # Profit factor
        metrics.profit_factor = (
            metrics.gross_profit / metrics.gross_loss
            if metrics.gross_loss > 0
            else float("inf")
        )

        # Expectancy
        metrics.expectancy = self._calculate_expectancy(closed_trades)

        # Return metrics
        metrics.total_return_pct = (metrics.total_pnl / self.initial_capital) * 100

        # Calculate CAGR
        if closed_trades:
            start_date = min(t.entry_date for t in closed_trades)
            end_date = max(t.exit_date for t in closed_trades if t.exit_date)
            if end_date:
                years = max(0.1, (end_date - start_date).days / 365)
                final_value = self.initial_capital + metrics.total_pnl
                metrics.cagr = (
                    (final_value / self.initial_capital) ** (1 / years) - 1
                ) * 100

        # Build equity curve and calculate risk metrics
        equity_curve = self._build_equity_curve(closed_trades)
        daily_returns = self._calculate_daily_returns(equity_curve)

        if daily_returns:
            metrics.volatility = self._calculate_volatility(daily_returns, equity_curve)
            metrics.sharpe_ratio = self._calculate_sharpe(daily_returns, equity_curve)
            metrics.sortino_ratio = self._calculate_sortino(daily_returns, equity_curve)

        # Drawdown metrics
        dd_metrics = self._calculate_drawdown(equity_curve)
        metrics.max_drawdown = dd_metrics["max_drawdown"]
        metrics.max_drawdown_pct = dd_metrics["max_drawdown_pct"]
        metrics.max_drawdown_duration_days = dd_metrics["max_duration"]

        # Calmar ratio (CAGR / Max Drawdown)
        if metrics.max_drawdown_pct > 0:
            metrics.calmar_ratio = metrics.cagr / metrics.max_drawdown_pct

        # Ret/DD (Return to Drawdown ratio)
        if metrics.max_drawdown_pct > 0:
            metrics.ret_dd = metrics.total_return_pct / metrics.max_drawdown_pct

        # SQN (System Quality Number - Van Tharp)
        metrics.sqn = self._calculate_sqn(closed_trades)

        # Trade duration metrics
        durations = [t.days_in_trade for t in closed_trades]
        metrics.avg_days_in_trade = sum(durations) / len(durations) if durations else 0

        winner_durations = [t.days_in_trade for t in winners]
        loser_durations = [t.days_in_trade for t in losers]

        metrics.avg_days_winner = (
            sum(winner_durations) / len(winner_durations) if winner_durations else 0
        )
        metrics.avg_days_loser = (
            sum(loser_durations) / len(loser_durations) if loser_durations else 0
        )

        # Consecutive wins/losses
        metrics.max_consecutive_wins, metrics.max_consecutive_losses = (
            self._calculate_consecutive(closed_trades)
        )

        # Exit reason breakdown
        metrics.exits_by_reason = self._count_exits_by_reason(closed_trades)

        # Per-symbol breakdown
        metrics.metrics_by_symbol = self._calculate_per_symbol(closed_trades)

        return metrics

    def _calculate_expectancy(self, trades: List[SimulatedTrade]) -> float:
        """Calculate expectancy (expected value per trade).

        Expectancy = (Win Rate × Avg Win) - (Loss Rate × Avg Loss)
        """
        if not trades:
            return 0

        winners = [t for t in trades if t.final_pnl > 0]
        losers = [t for t in trades if t.final_pnl <= 0]

        win_rate = len(winners) / len(trades) if trades else 0
        loss_rate = 1 - win_rate

        avg_win = sum(t.final_pnl for t in winners) / len(winners) if winners else 0
        avg_loss = abs(sum(t.final_pnl for t in losers)) / len(losers) if losers else 0

        return (win_rate * avg_win) - (loss_rate * avg_loss)

    def _calculate_sqn(self, trades: List[SimulatedTrade]) -> float:
        """Calculate System Quality Number (Van Tharp).

        SQN = √N × (Mean R / StdDev R)

        Where R = R-multiple = P&L / Risk per trade

        SQN interpretation (Van Tharp):
        - < 1.6: Poor, hard to trade profitably
        - 1.6-2.0: Below average
        - 2.0-2.5: Average
        - 2.5-3.0: Good
        - 3.0-5.0: Excellent
        - 5.0-7.0: Superb
        - > 7.0: Holy Grail (probably curve-fitted)
        """
        if len(trades) < 2:
            return 0.0

        # Calculate R-multiples (P&L / max_risk)
        r_multiples = []
        for trade in trades:
            if trade.max_risk > 0:
                r = trade.final_pnl / trade.max_risk
                r_multiples.append(r)

        if len(r_multiples) < 2:
            return 0.0

        # Calculate mean and standard deviation of R-multiples
        mean_r = sum(r_multiples) / len(r_multiples)
        variance = sum((r - mean_r) ** 2 for r in r_multiples) / len(r_multiples)
        std_r = math.sqrt(variance)

        if std_r == 0:
            return 0.0

        # SQN = √N × (Mean R / Std R)
        # Cap N at 100 to normalize SQN (Van Tharp's standard sample size)
        # This prevents inflated SQN values when trading many symbols/trades
        capped_n = min(100, len(r_multiples))
        sqn = math.sqrt(capped_n) * (mean_r / std_r)

        return sqn

    def _build_equity_curve(
        self, trades: List[SimulatedTrade]
    ) -> List[Tuple[date, float]]:
        """Build equity curve from trades.

        Returns list of (date, equity) tuples sorted by date.
        """
        # Sort trades by exit date
        sorted_trades = sorted(
            [t for t in trades if t.exit_date],
            key=lambda t: t.exit_date,
        )

        equity_curve = []
        cumulative_pnl = self.initial_capital

        for trade in sorted_trades:
            cumulative_pnl += trade.final_pnl
            equity_curve.append((trade.exit_date, cumulative_pnl))

        return equity_curve

    def _calculate_daily_returns(
        self, equity_curve: List[Tuple[date, float]]
    ) -> List[float]:
        """Calculate daily returns from equity curve."""
        if len(equity_curve) < 2:
            return []

        returns = []
        for i in range(1, len(equity_curve)):
            prev_equity = equity_curve[i - 1][1]
            curr_equity = equity_curve[i][1]
            if prev_equity > 0:
                daily_return = (curr_equity - prev_equity) / prev_equity
                returns.append(daily_return)

        return returns

    def _calculate_volatility(
        self, returns: List[float], equity_curve: List[Tuple[date, float]] = None
    ) -> float:
        """Calculate annualized volatility from returns."""
        if not returns:
            return 0

        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std_dev = math.sqrt(variance)

        # Annualize based on actual trading period
        trades_per_year = self._estimate_trades_per_year(len(returns), equity_curve)
        annualized_vol = std_dev * math.sqrt(trades_per_year)

        return annualized_vol * 100  # As percentage

    def _estimate_trades_per_year(
        self, num_trades: int, equity_curve: List[Tuple[date, float]] = None
    ) -> float:
        """Estimate annualized number of trades based on actual period.

        Uses equity curve dates to determine the actual trading period length.
        """
        if not equity_curve or len(equity_curve) < 2:
            # Fallback: assume average of 1 trade per week
            return min(52, num_trades)

        # Get actual period from equity curve dates
        first_date = equity_curve[0][0]
        last_date = equity_curve[-1][0]
        period_days = (last_date - first_date).days

        if period_days <= 0:
            return min(52, num_trades)

        # Calculate trades per year based on actual period
        # period_days / 365 = fraction of year
        # num_trades / fraction = trades per year
        fraction_of_year = period_days / 365.0
        trades_per_year = num_trades / fraction_of_year

        # Cap at reasonable maximum (no more than weekly trades per symbol)
        return min(252, trades_per_year)

    def _calculate_sharpe(
        self, returns: List[float], equity_curve: List[Tuple[date, float]] = None
    ) -> float:
        """Calculate Sharpe ratio.

        Sharpe = (Returns - Risk Free) / Volatility
        """
        if not returns:
            return 0

        mean_return = sum(returns) / len(returns)
        volatility = self._calculate_volatility(returns, equity_curve) / 100

        if volatility == 0:
            return 0

        # Annualize mean return based on actual trading period
        trades_per_year = self._estimate_trades_per_year(len(returns), equity_curve)
        annual_return = mean_return * trades_per_year

        return (annual_return - self.RISK_FREE_RATE) / volatility

    def _calculate_sortino(
        self, returns: List[float], equity_curve: List[Tuple[date, float]] = None
    ) -> float:
        """Calculate Sortino ratio (penalizes only downside volatility).

        Sortino = (Returns - Risk Free) / Downside Deviation
        """
        if not returns:
            return 0

        mean_return = sum(returns) / len(returns)

        # Calculate downside deviation (only negative returns)
        negative_returns = [r for r in returns if r < 0]
        if not negative_returns:
            return float("inf")

        downside_variance = sum(r ** 2 for r in negative_returns) / len(returns)
        downside_dev = math.sqrt(downside_variance)

        if downside_dev == 0:
            return float("inf")

        # Annualize based on actual trading period
        trades_per_year = self._estimate_trades_per_year(len(returns), equity_curve)
        annual_return = mean_return * trades_per_year
        annual_downside = downside_dev * math.sqrt(trades_per_year)

        return (annual_return - self.RISK_FREE_RATE) / annual_downside

    def _calculate_drawdown(
        self, equity_curve: List[Tuple[date, float]]
    ) -> Dict[str, float]:
        """Calculate maximum drawdown and duration."""
        if not equity_curve:
            return {"max_drawdown": 0, "max_drawdown_pct": 0, "max_duration": 0}

        peak = equity_curve[0][1]
        max_drawdown = 0
        max_drawdown_pct = 0
        max_duration = 0

        current_drawdown_start = None
        current_duration = 0

        for dt, equity in equity_curve:
            if equity > peak:
                peak = equity
                current_drawdown_start = None
                current_duration = 0
            else:
                drawdown = peak - equity
                drawdown_pct = (drawdown / peak) * 100 if peak > 0 else 0

                if drawdown > max_drawdown:
                    max_drawdown = drawdown
                    max_drawdown_pct = drawdown_pct

                if current_drawdown_start is None:
                    current_drawdown_start = dt
                else:
                    current_duration = (dt - current_drawdown_start).days
                    if current_duration > max_duration:
                        max_duration = current_duration

        return {
            "max_drawdown": max_drawdown,
            "max_drawdown_pct": max_drawdown_pct,
            "max_duration": max_duration,
        }

    def _calculate_consecutive(
        self, trades: List[SimulatedTrade]
    ) -> Tuple[int, int]:
        """Calculate max consecutive wins and losses."""
        if not trades:
            return 0, 0

        # Sort by exit date
        sorted_trades = sorted(
            [t for t in trades if t.exit_date],
            key=lambda t: t.exit_date,
        )

        max_wins = 0
        max_losses = 0
        current_wins = 0
        current_losses = 0

        for trade in sorted_trades:
            if trade.final_pnl > 0:
                current_wins += 1
                current_losses = 0
                max_wins = max(max_wins, current_wins)
            else:
                current_losses += 1
                current_wins = 0
                max_losses = max(max_losses, current_losses)

        return max_wins, max_losses

    def _count_exits_by_reason(
        self, trades: List[SimulatedTrade]
    ) -> Dict[str, int]:
        """Count trades by exit reason."""
        counts: Dict[str, int] = defaultdict(int)
        for trade in trades:
            if trade.exit_reason:
                counts[trade.exit_reason.value] += 1
        return dict(counts)

    def _calculate_per_symbol(
        self, trades: List[SimulatedTrade]
    ) -> Dict[str, Dict[str, Any]]:
        """Calculate metrics breakdown per symbol.

        Includes: total_trades, win_rate, total_pnl, avg_pnl,
        avg_winner, avg_loser, profit_factor, sharpe_ratio.
        """
        by_symbol: Dict[str, List[SimulatedTrade]] = defaultdict(list)
        for trade in trades:
            by_symbol[trade.symbol].append(trade)

        results: Dict[str, Dict[str, Any]] = {}
        for symbol, symbol_trades in by_symbol.items():
            winners = [t for t in symbol_trades if t.final_pnl > 0]
            losers = [t for t in symbol_trades if t.final_pnl <= 0]
            total_pnl = sum(t.final_pnl for t in symbol_trades)

            # Basic metrics
            total_trades = len(symbol_trades)
            win_rate = len(winners) / total_trades if total_trades else 0

            # Avg winner / loser
            avg_winner = (
                sum(t.final_pnl for t in winners) / len(winners) if winners else 0
            )
            avg_loser = (
                abs(sum(t.final_pnl for t in losers)) / len(losers) if losers else 0
            )

            # Profit factor
            gross_profit = sum(t.final_pnl for t in winners)
            gross_loss = abs(sum(t.final_pnl for t in losers))
            profit_factor = (
                gross_profit / gross_loss if gross_loss > 0 else float("inf")
            )

            # Sharpe ratio for this symbol
            sharpe_ratio = self._calculate_symbol_sharpe(symbol_trades)

            results[symbol] = {
                "total_trades": total_trades,
                "win_rate": win_rate,
                "total_pnl": total_pnl,
                "avg_pnl": total_pnl / total_trades if total_trades else 0,
                "avg_winner": avg_winner,
                "avg_loser": avg_loser,
                "profit_factor": profit_factor,
                "sharpe_ratio": sharpe_ratio,
            }

        return results

    def _calculate_symbol_sharpe(self, trades: List[SimulatedTrade]) -> float:
        """Calculate Sharpe ratio for a single symbol's trades."""
        if len(trades) < 2:
            return 0.0

        # Build equity curve for this symbol
        equity_curve = self._build_equity_curve(trades)
        returns = self._calculate_daily_returns(equity_curve)

        if not returns:
            return 0.0

        return self._calculate_sharpe(returns, equity_curve)


def calculate_degradation_score(
    in_sample: PerformanceMetrics,
    out_sample: PerformanceMetrics,
) -> Optional[float]:
    """Calculate performance degradation between in-sample and out-of-sample.

    A lower score is better (less degradation).
    Only measures degradation when out-of-sample is WORSE than in-sample.
    If out-of-sample performs better, degradation = 0 (no overfitting detected).

    Returns:
        Degradation score as percentage (0 = no degradation, 100 = total loss)
        Returns None if out-of-sample has no trades (cannot calculate degradation)
    """
    # Cannot calculate degradation without out-of-sample trades
    if out_sample.total_trades == 0:
        return None

    if in_sample.sharpe_ratio == 0:
        return 100.0 if out_sample.sharpe_ratio <= 0 else 0.0

    # Primary metric: Sharpe ratio degradation (only if worse)
    if out_sample.sharpe_ratio >= in_sample.sharpe_ratio:
        sharpe_degradation = 0.0  # No degradation if out-of-sample is better
    else:
        sharpe_degradation = (
            (in_sample.sharpe_ratio - out_sample.sharpe_ratio) / in_sample.sharpe_ratio
        )

    # Secondary: Win rate degradation (only if worse)
    if in_sample.win_rate > 0:
        if out_sample.win_rate >= in_sample.win_rate:
            winrate_degradation = 0.0  # No degradation if out-of-sample is better
        else:
            winrate_degradation = (
                (in_sample.win_rate - out_sample.win_rate) / in_sample.win_rate
            )
    else:
        winrate_degradation = 0

    # Combine (weighted average)
    degradation = (sharpe_degradation * 0.7 + winrate_degradation * 0.3) * 100

    return min(100, max(0, degradation))


__all__ = ["MetricsCalculator", "calculate_degradation_score"]
