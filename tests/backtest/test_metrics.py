"""Tests for tomic.backtest.metrics module."""

from __future__ import annotations

import math
import pytest
from datetime import date, timedelta

from tomic.backtest.metrics import MetricsCalculator, calculate_degradation_score
from tomic.backtest.results import (
    SimulatedTrade,
    TradeStatus,
    ExitReason,
    PerformanceMetrics,
)


def approx(a: float, b: float, rel: float = 0.01) -> bool:
    """Check if two floats are approximately equal."""
    if a == b:
        return True
    if b == 0:
        return abs(a) < rel
    return abs(a - b) / abs(b) < rel


def make_trade(
    entry_date: date,
    exit_date: date,
    final_pnl: float,
    max_risk: float = 200.0,
    status: TradeStatus = TradeStatus.CLOSED,
    exit_reason: ExitReason = ExitReason.PROFIT_TARGET,
) -> SimulatedTrade:
    """Helper to create a SimulatedTrade for testing."""
    trade = SimulatedTrade(
        entry_date=entry_date,
        symbol="SPY",
        strategy_type="iron_condor",
        iv_at_entry=0.20,
        iv_percentile_at_entry=70.0,
        iv_rank_at_entry=65.0,
        spot_at_entry=450.0,
        target_expiry=entry_date + timedelta(days=45),
        max_risk=max_risk,
        estimated_credit=50.0,
    )
    trade.status = status
    trade.exit_date = exit_date
    trade.exit_reason = exit_reason
    trade.final_pnl = final_pnl
    trade.days_in_trade = (exit_date - entry_date).days
    return trade


class TestMetricsCalculator:
    """Tests for MetricsCalculator class."""

    def test_calculate_returns_empty_metrics_for_no_trades(self):
        """Should return default metrics when no trades."""
        calc = MetricsCalculator()

        result = calc.calculate([])

        assert result.total_trades == 0
        assert result.win_rate == 0
        assert result.total_pnl == 0

    def test_calculate_returns_empty_metrics_for_open_trades(self):
        """Should ignore open trades."""
        calc = MetricsCalculator()
        trade = make_trade(
            date(2024, 1, 1),
            date(2024, 1, 15),
            50.0,
            status=TradeStatus.OPEN,
        )

        result = calc.calculate([trade])

        assert result.total_trades == 0

    def test_basic_counts(self):
        """Should count trades correctly."""
        calc = MetricsCalculator()
        trades = [
            make_trade(date(2024, 1, 1), date(2024, 1, 15), 50.0),  # Winner
            make_trade(date(2024, 1, 20), date(2024, 2, 5), 30.0),  # Winner
            make_trade(date(2024, 2, 10), date(2024, 2, 25), -100.0),  # Loser
        ]

        result = calc.calculate(trades)

        assert result.total_trades == 3
        assert result.winning_trades == 2
        assert result.losing_trades == 1
        assert approx(result.win_rate, 2 / 3)

    def test_pnl_metrics(self):
        """Should calculate P&L metrics correctly."""
        calc = MetricsCalculator()
        trades = [
            make_trade(date(2024, 1, 1), date(2024, 1, 15), 100.0),
            make_trade(date(2024, 1, 20), date(2024, 2, 5), 50.0),
            make_trade(date(2024, 2, 10), date(2024, 2, 25), -75.0),
        ]

        result = calc.calculate(trades)

        assert approx(result.total_pnl, 75.0)  # 100+50-75
        assert approx(result.gross_profit, 150.0)  # 100+50
        assert approx(result.gross_loss, 75.0)  # abs(-75)
        assert approx(result.average_pnl, 25.0)  # 75/3

    def test_average_winner_loser(self):
        """Should calculate average winner and loser."""
        calc = MetricsCalculator()
        trades = [
            make_trade(date(2024, 1, 1), date(2024, 1, 15), 100.0),
            make_trade(date(2024, 1, 20), date(2024, 2, 5), 50.0),
            make_trade(date(2024, 2, 10), date(2024, 2, 25), -75.0),
        ]

        result = calc.calculate(trades)

        assert approx(result.average_winner, 75.0)  # (100+50)/2
        assert approx(result.average_loser, 75.0)  # abs(-75)/1

    def test_profit_factor(self):
        """Should calculate profit factor correctly."""
        calc = MetricsCalculator()
        trades = [
            make_trade(date(2024, 1, 1), date(2024, 1, 15), 100.0),
            make_trade(date(2024, 2, 10), date(2024, 2, 25), -50.0),
        ]

        result = calc.calculate(trades)

        assert approx(result.profit_factor, 2.0)  # 100/50

    def test_profit_factor_inf_for_no_losses(self):
        """Profit factor should be inf when no losses."""
        calc = MetricsCalculator()
        trades = [
            make_trade(date(2024, 1, 1), date(2024, 1, 15), 100.0),
        ]

        result = calc.calculate(trades)

        assert result.profit_factor == float("inf")

    def test_expectancy_calculation(self):
        """Should calculate expectancy."""
        calc = MetricsCalculator()
        # 2 winners at $50, 1 loser at -$100
        # Win rate = 2/3, Avg win = 50, Avg loss = 100
        # Expectancy = (2/3 * 50) - (1/3 * 100) = 33.33 - 33.33 = 0
        trades = [
            make_trade(date(2024, 1, 1), date(2024, 1, 15), 50.0),
            make_trade(date(2024, 1, 20), date(2024, 2, 5), 50.0),
            make_trade(date(2024, 2, 10), date(2024, 2, 25), -100.0),
        ]

        result = calc.calculate(trades)

        expected = (2 / 3 * 50) - (1 / 3 * 100)
        assert approx(result.expectancy, expected, rel=0.05)

    def test_return_metrics(self):
        """Should calculate return percentages."""
        calc = MetricsCalculator(initial_capital=10000.0)
        trades = [
            make_trade(date(2024, 1, 1), date(2024, 1, 15), 500.0),
        ]

        result = calc.calculate(trades)

        assert approx(result.total_return_pct, 5.0)  # 500/10000 * 100

    def test_trade_duration_metrics(self):
        """Should calculate average days in trade."""
        calc = MetricsCalculator()
        trades = [
            make_trade(date(2024, 1, 1), date(2024, 1, 11), 50.0),  # 10 days winner
            make_trade(date(2024, 1, 15), date(2024, 2, 4), -50.0),  # 20 days loser
        ]

        result = calc.calculate(trades)

        assert approx(result.avg_days_in_trade, 15.0)  # (10+20)/2
        assert approx(result.avg_days_winner, 10.0)
        assert approx(result.avg_days_loser, 20.0)

    def test_consecutive_wins_losses(self):
        """Should track max consecutive wins and losses."""
        calc = MetricsCalculator()
        trades = [
            make_trade(date(2024, 1, 1), date(2024, 1, 5), 50.0),  # Win
            make_trade(date(2024, 1, 6), date(2024, 1, 10), 50.0),  # Win
            make_trade(date(2024, 1, 11), date(2024, 1, 15), 50.0),  # Win
            make_trade(date(2024, 1, 16), date(2024, 1, 20), -50.0),  # Loss
            make_trade(date(2024, 1, 21), date(2024, 1, 25), -50.0),  # Loss
            make_trade(date(2024, 1, 26), date(2024, 1, 30), 50.0),  # Win
        ]

        result = calc.calculate(trades)

        assert result.max_consecutive_wins == 3
        assert result.max_consecutive_losses == 2

    def test_exit_reason_breakdown(self):
        """Should count exits by reason."""
        calc = MetricsCalculator()
        trades = [
            make_trade(date(2024, 1, 1), date(2024, 1, 15), 50.0, exit_reason=ExitReason.PROFIT_TARGET),
            make_trade(date(2024, 1, 20), date(2024, 2, 5), -50.0, exit_reason=ExitReason.STOP_LOSS),
            make_trade(date(2024, 2, 10), date(2024, 2, 25), 30.0, exit_reason=ExitReason.PROFIT_TARGET),
        ]

        result = calc.calculate(trades)

        assert result.exits_by_reason[ExitReason.PROFIT_TARGET.value] == 2
        assert result.exits_by_reason[ExitReason.STOP_LOSS.value] == 1

    def test_per_symbol_breakdown(self):
        """Should calculate metrics per symbol."""
        calc = MetricsCalculator()
        trades = [
            make_trade(date(2024, 1, 1), date(2024, 1, 15), 50.0),
            make_trade(date(2024, 1, 20), date(2024, 2, 5), 30.0),
        ]
        trades[1].symbol = "QQQ"

        result = calc.calculate(trades)

        assert "SPY" in result.metrics_by_symbol
        assert "QQQ" in result.metrics_by_symbol
        assert result.metrics_by_symbol["SPY"]["total_pnl"] == 50.0
        assert result.metrics_by_symbol["QQQ"]["total_pnl"] == 30.0

    def test_sqn_calculation(self):
        """Should calculate System Quality Number."""
        calc = MetricsCalculator()
        # Create trades with varying R-multiples
        trades = [
            make_trade(date(2024, 1, i), date(2024, 1, i + 5), pnl, max_risk=100.0)
            for i, pnl in enumerate([50, 40, 60, -30, 55, 45, -25, 70, 35, 50], start=1)
        ]

        result = calc.calculate(trades)

        # SQN should be positive for this profitable series
        assert result.sqn > 0

    def test_sqn_returns_zero_for_single_trade(self):
        """SQN needs at least 2 trades."""
        calc = MetricsCalculator()
        trades = [make_trade(date(2024, 1, 1), date(2024, 1, 15), 50.0)]

        result = calc.calculate(trades)

        assert result.sqn == 0.0

    def test_drawdown_calculation(self):
        """Should calculate max drawdown."""
        calc = MetricsCalculator(initial_capital=10000.0)
        # Sequence: +100, -300, -200, +400 (net: 0)
        # Equity: 10100, 9800, 9600, 10000
        # Drawdown from 10100 to 9600 = 500 (4.95%)
        trades = [
            make_trade(date(2024, 1, 1), date(2024, 1, 5), 100.0),
            make_trade(date(2024, 1, 6), date(2024, 1, 10), -300.0),
            make_trade(date(2024, 1, 11), date(2024, 1, 15), -200.0),
            make_trade(date(2024, 1, 16), date(2024, 1, 20), 400.0),
        ]

        result = calc.calculate(trades)

        assert result.max_drawdown > 0
        assert result.max_drawdown_pct > 0

    def test_sharpe_ratio_calculation(self):
        """Should calculate Sharpe ratio."""
        calc = MetricsCalculator(initial_capital=10000.0)
        # Consistent wins should give positive Sharpe
        base = date(2024, 1, 1)
        trades = [
            make_trade(base + timedelta(days=i * 7), base + timedelta(days=i * 7 + 5), 50.0)
            for i in range(8)
        ]

        result = calc.calculate(trades)

        # With consistent positive returns, Sharpe should be calculated
        # (may be zero if volatility is zero)
        assert isinstance(result.sharpe_ratio, (int, float))

    def test_sortino_ratio_calculation(self):
        """Should calculate Sortino ratio."""
        calc = MetricsCalculator(initial_capital=10000.0)
        base = date(2024, 1, 1)
        trades = [
            make_trade(base + timedelta(days=i * 7), base + timedelta(days=i * 7 + 5), 50.0)
            for i in range(8)
        ]

        result = calc.calculate(trades)

        # All positive returns means inf Sortino (no downside)
        assert result.sortino_ratio == float("inf") or result.sortino_ratio > 0

    def test_handles_trades_with_zero_max_risk(self):
        """Should handle trades with zero max_risk in SQN calculation."""
        calc = MetricsCalculator()
        trades = [
            make_trade(date(2024, 1, 1), date(2024, 1, 15), 50.0, max_risk=0.0),
            make_trade(date(2024, 1, 20), date(2024, 2, 5), 30.0, max_risk=0.0),
        ]

        result = calc.calculate(trades)

        # Should not crash
        assert result.sqn == 0.0  # No valid R-multiples


class TestCalculateDegradationScore:
    """Tests for calculate_degradation_score function."""

    def test_returns_none_when_no_out_sample_trades(self):
        """Should return None when out-sample has no trades."""
        in_sample = PerformanceMetrics(
            total_trades=10,
            win_rate=0.7,
            sharpe_ratio=1.5,
        )
        out_sample = PerformanceMetrics(
            total_trades=0,
            win_rate=0,
            sharpe_ratio=0,
        )

        result = calculate_degradation_score(in_sample, out_sample)

        assert result is None

    def test_returns_zero_when_out_sample_better(self):
        """Should return 0 (no degradation) when out-sample is better."""
        in_sample = PerformanceMetrics(
            total_trades=10,
            win_rate=0.6,
            sharpe_ratio=1.0,
        )
        out_sample = PerformanceMetrics(
            total_trades=10,
            win_rate=0.7,
            sharpe_ratio=1.5,
        )

        result = calculate_degradation_score(in_sample, out_sample)

        assert result == 0.0

    def test_calculates_degradation_when_out_sample_worse(self):
        """Should calculate degradation when out-sample is worse."""
        in_sample = PerformanceMetrics(
            total_trades=10,
            win_rate=0.7,
            sharpe_ratio=2.0,
        )
        out_sample = PerformanceMetrics(
            total_trades=10,
            win_rate=0.5,
            sharpe_ratio=1.0,
        )

        result = calculate_degradation_score(in_sample, out_sample)

        assert result > 0
        assert result <= 100

    def test_returns_100_when_in_sample_sharpe_zero_and_out_negative(self):
        """Edge case: in-sample Sharpe is zero."""
        in_sample = PerformanceMetrics(
            total_trades=10,
            sharpe_ratio=0.0,
        )
        out_sample = PerformanceMetrics(
            total_trades=10,
            sharpe_ratio=-0.5,
        )

        result = calculate_degradation_score(in_sample, out_sample)

        assert result == 100.0

    def test_returns_zero_when_in_sample_sharpe_zero_and_out_positive(self):
        """Edge case: in-sample Sharpe is zero but out is positive."""
        in_sample = PerformanceMetrics(
            total_trades=10,
            sharpe_ratio=0.0,
        )
        out_sample = PerformanceMetrics(
            total_trades=10,
            sharpe_ratio=0.5,
        )

        result = calculate_degradation_score(in_sample, out_sample)

        assert result == 0.0

    def test_weights_sharpe_more_than_winrate(self):
        """Sharpe degradation should be weighted at 70%."""
        # Only Sharpe degraded
        in_sample = PerformanceMetrics(
            total_trades=10,
            win_rate=0.5,
            sharpe_ratio=2.0,
        )
        out_sample = PerformanceMetrics(
            total_trades=10,
            win_rate=0.5,
            sharpe_ratio=1.0,  # 50% degradation
        )

        result = calculate_degradation_score(in_sample, out_sample)

        # 50% Sharpe degradation * 0.7 + 0% winrate degradation * 0.3 = 35%
        assert approx(result, 35.0, rel=0.15)

    def test_clamps_result_between_0_and_100(self):
        """Result should be clamped to [0, 100]."""
        in_sample = PerformanceMetrics(
            total_trades=10,
            win_rate=0.9,
            sharpe_ratio=3.0,
        )
        out_sample = PerformanceMetrics(
            total_trades=10,
            win_rate=0.1,
            sharpe_ratio=-1.0,
        )

        result = calculate_degradation_score(in_sample, out_sample)

        assert 0 <= result <= 100
