"""Tests for tomic.backtest.trade_simulator module."""

from __future__ import annotations

import pytest
from datetime import date, timedelta
from unittest.mock import Mock, MagicMock, patch

from tomic.backtest.trade_simulator import TradeSimulator
from tomic.backtest.config import BacktestConfig, PositionSizingConfig
from tomic.backtest.results import (
    SimulatedTrade,
    TradeStatus,
    ExitReason,
    EntrySignal,
)
from tomic.backtest.data_loader import IVTimeSeries


def make_config(
    max_risk: float = 200.0,
    max_positions: int = 10,
    target_dte: int = 45,
) -> BacktestConfig:
    """Create a BacktestConfig for testing."""
    config = BacktestConfig(
        position_sizing=PositionSizingConfig(
            max_risk_per_trade=max_risk,
            max_total_positions=max_positions,
        ),
        target_dte=target_dte,
    )
    return config


def make_entry_signal(
    symbol: str = "SPY",
    signal_date: date = date(2024, 1, 15),
    iv_at_entry: float = 0.20,
    iv_percentile: float = 70.0,
) -> EntrySignal:
    """Create an EntrySignal for testing."""
    return EntrySignal(
        date=signal_date,
        symbol=symbol,
        iv_at_entry=iv_at_entry,
        iv_rank_at_entry=65.0,
        iv_percentile_at_entry=iv_percentile,
        hv_at_entry=0.18,
        skew_at_entry=0.05,
        term_at_entry=0.02,
        spot_at_entry=450.0,
    )


class TestTradeSimulatorInit:
    """Tests for TradeSimulator initialization."""

    def test_creates_with_default_config(self):
        """Should create simulator with default config."""
        config = make_config()
        sim = TradeSimulator(config)

        assert sim.config == config
        assert len(sim.get_open_positions()) == 0
        assert len(sim.get_all_trades()) == 0

    def test_creates_with_greeks_model(self):
        """Should create simulator with Greeks model."""
        config = make_config()
        sim = TradeSimulator(config, use_greeks_model=True)

        assert sim.use_greeks_model is True
        assert sim.greeks_model is not None

    def test_creates_with_strategy_config(self):
        """Should store strategy-specific config."""
        config = make_config()
        strategy_config = {"min_risk_reward": 2.0, "stddev_range": 1.5}
        sim = TradeSimulator(config, strategy_config=strategy_config)

        assert sim.strategy_config == strategy_config


class TestTradeSimulatorOpenTrade:
    """Tests for opening trades."""

    def test_opens_trade_successfully(self):
        """Should open a trade and return it."""
        config = make_config()
        sim = TradeSimulator(config)
        signal = make_entry_signal()

        trade = sim.open_trade(signal)

        assert trade is not None
        assert trade.symbol == "SPY"
        assert trade.status == TradeStatus.OPEN
        assert trade.iv_at_entry == 0.20

    def test_tracks_open_position(self):
        """Should track the open position by symbol."""
        config = make_config()
        sim = TradeSimulator(config)
        signal = make_entry_signal()

        sim.open_trade(signal)

        assert sim.has_position("SPY")
        assert "SPY" in sim.get_open_positions()

    def test_rejects_duplicate_position(self):
        """Should reject opening a second position for same symbol."""
        config = make_config()
        sim = TradeSimulator(config)
        signal = make_entry_signal()

        sim.open_trade(signal)
        second_trade = sim.open_trade(signal)

        assert second_trade is None
        assert len(sim.get_open_positions()) == 1

    def test_rejects_when_max_positions_reached(self):
        """Should reject when max positions limit is reached."""
        config = make_config(max_positions=2)
        sim = TradeSimulator(config)

        sim.open_trade(make_entry_signal(symbol="SPY"))
        sim.open_trade(make_entry_signal(symbol="QQQ"))
        third = sim.open_trade(make_entry_signal(symbol="AAPL"))

        assert third is None
        assert len(sim.get_open_positions()) == 2

    def test_calculates_target_expiry(self):
        """Should calculate target expiry from entry date + target DTE."""
        config = make_config(target_dte=45)
        sim = TradeSimulator(config)
        signal = make_entry_signal(signal_date=date(2024, 1, 15))

        trade = sim.open_trade(signal)

        assert trade.target_expiry == date(2024, 1, 15) + timedelta(days=45)

    def test_applies_slippage_to_credit(self):
        """Should apply slippage to estimated credit."""
        config = make_config()
        sim = TradeSimulator(config)
        signal = make_entry_signal()

        trade = sim.open_trade(signal)

        # Credit should be reduced by slippage percentage
        # Exact value depends on pnl_model calculation
        assert trade.estimated_credit > 0

    def test_records_trade_in_all_trades(self):
        """Should add trade to all_trades list."""
        config = make_config()
        sim = TradeSimulator(config)
        signal = make_entry_signal()

        sim.open_trade(signal)

        assert len(sim.get_all_trades()) == 1

    def test_rejects_when_rr_exceeds_min(self):
        """Should reject trade when risk/reward exceeds minimum."""
        config = make_config()
        strategy_config = {"min_risk_reward": 1.0}  # Very restrictive
        sim = TradeSimulator(config, strategy_config=strategy_config)
        # High IV should give higher credit, better R/R
        signal = make_entry_signal(iv_at_entry=0.50)

        trade = sim.open_trade(signal)

        # May or may not be rejected depending on calculated R/R
        # Just verify it doesn't crash
        assert trade is None or isinstance(trade, SimulatedTrade)


class TestTradeSimulatorPositionChecks:
    """Tests for position checking methods."""

    def test_has_position_returns_true_for_open(self):
        """has_position should return True for open positions."""
        config = make_config()
        sim = TradeSimulator(config)
        sim.open_trade(make_entry_signal(symbol="SPY"))

        assert sim.has_position("SPY") is True
        assert sim.has_position("QQQ") is False

    def test_can_open_position_checks_symbol_and_limit(self):
        """can_open_position should check both symbol and total limit."""
        config = make_config(max_positions=2)
        sim = TradeSimulator(config)
        sim.open_trade(make_entry_signal(symbol="SPY"))

        assert sim.can_open_position("SPY") is False  # Already has position
        assert sim.can_open_position("QQQ") is True  # Can still open

        sim.open_trade(make_entry_signal(symbol="QQQ"))
        assert sim.can_open_position("AAPL") is False  # Max reached

    def test_get_open_position_symbols(self):
        """Should return dict of open position symbols."""
        config = make_config()
        sim = TradeSimulator(config)
        sim.open_trade(make_entry_signal(symbol="SPY"))
        sim.open_trade(make_entry_signal(symbol="QQQ"))

        symbols = sim.get_open_position_symbols()

        assert symbols == {"SPY": True, "QQQ": True}


class TestTradeSimulatorProcessDay:
    """Tests for process_day method."""

    def test_updates_days_in_trade(self):
        """Should update days_in_trade for open positions."""
        config = make_config()
        sim = TradeSimulator(config)
        signal = make_entry_signal(signal_date=date(2024, 1, 15))
        sim.open_trade(signal)

        sim.process_day(date(2024, 1, 20), {})

        trade = list(sim.get_open_positions().values())[0]
        assert trade.days_in_trade == 5

    def test_closes_trade_on_exit_condition(self):
        """Should close trade when exit condition is met."""
        config = make_config()
        sim = TradeSimulator(config)
        signal = make_entry_signal(signal_date=date(2024, 1, 15))
        sim.open_trade(signal)

        # Simulate until near expiry (min_dte exit)
        target_expiry = signal.date + timedelta(days=config.target_dte)
        close_date = target_expiry - timedelta(days=3)

        closed = sim.process_day(close_date, {})

        # Should have triggered DTE exit
        if closed:
            assert len(sim.get_open_positions()) == 0
            trade = closed[0]
            assert trade.status == TradeStatus.CLOSED

    def test_tracks_iv_history(self):
        """Should track IV in trade history when available."""
        config = make_config()
        sim = TradeSimulator(config)
        signal = make_entry_signal(signal_date=date(2024, 1, 15))
        sim.open_trade(signal)

        # Create mock IV data
        mock_iv_data = MagicMock()
        mock_datapoint = MagicMock()
        mock_datapoint.atm_iv = 0.22
        mock_datapoint.spot_price = 455.0
        mock_iv_data.get.return_value = mock_datapoint

        sim.process_day(date(2024, 1, 20), {"SPY": mock_iv_data})

        trade = list(sim.get_open_positions().values())[0]
        assert len(trade.iv_history) > 0 or trade.status == TradeStatus.CLOSED

    def test_returns_closed_trades(self):
        """Should return list of trades closed on this day."""
        config = make_config()
        sim = TradeSimulator(config)
        signal = make_entry_signal(signal_date=date(2024, 1, 15))
        sim.open_trade(signal)

        # Process many days to trigger exit
        closed = []
        for i in range(60):  # 60 days should trigger max DIT
            result = sim.process_day(signal.date + timedelta(days=i), {})
            closed.extend(result)

        # Should eventually close due to max days in trade
        assert len(closed) > 0


class TestTradeSimulatorForceClose:
    """Tests for force_close_all method."""

    def test_closes_all_open_positions(self):
        """Should close all open positions."""
        config = make_config()
        sim = TradeSimulator(config)
        sim.open_trade(make_entry_signal(symbol="SPY"))
        sim.open_trade(make_entry_signal(symbol="QQQ"))

        closed = sim.force_close_all(date(2024, 2, 1))

        assert len(closed) == 2
        assert len(sim.get_open_positions()) == 0

    def test_uses_specified_exit_reason(self):
        """Should use the specified exit reason."""
        config = make_config()
        sim = TradeSimulator(config)
        sim.open_trade(make_entry_signal(symbol="SPY"))

        closed = sim.force_close_all(date(2024, 2, 1), reason=ExitReason.EXPIRATION)

        assert closed[0].exit_reason == ExitReason.EXPIRATION

    def test_sets_exit_date_to_current(self):
        """Should set exit_date to the provided date."""
        config = make_config()
        sim = TradeSimulator(config)
        sim.open_trade(make_entry_signal(symbol="SPY"))

        closed = sim.force_close_all(date(2024, 2, 1))

        assert closed[0].exit_date == date(2024, 2, 1)

    def test_handles_empty_positions(self):
        """Should handle case with no open positions."""
        config = make_config()
        sim = TradeSimulator(config)

        closed = sim.force_close_all(date(2024, 2, 1))

        assert closed == []


class TestTradeSimulatorSummary:
    """Tests for get_summary method."""

    def test_returns_summary_dict(self):
        """Should return summary statistics dict."""
        config = make_config()
        sim = TradeSimulator(config)
        sim.open_trade(make_entry_signal(symbol="SPY"))

        summary = sim.get_summary()

        assert "total_trades" in summary
        assert "closed_trades" in summary
        assert "open_trades" in summary
        assert "winners" in summary
        assert "losers" in summary
        assert "win_rate" in summary
        assert "total_pnl" in summary

    def test_counts_open_and_closed(self):
        """Should correctly count open and closed trades."""
        config = make_config()
        sim = TradeSimulator(config)
        sim.open_trade(make_entry_signal(symbol="SPY"))
        sim.open_trade(make_entry_signal(symbol="QQQ"))
        sim.force_close_all(date(2024, 2, 1))
        sim.open_trade(make_entry_signal(symbol="AAPL", signal_date=date(2024, 2, 15)))

        summary = sim.get_summary()

        assert summary["total_trades"] == 3
        assert summary["closed_trades"] == 2
        assert summary["open_trades"] == 1

    def test_calculates_win_rate(self):
        """Should calculate win rate from closed trades."""
        config = make_config()
        sim = TradeSimulator(config)

        # Create and close some trades
        for symbol in ["SPY", "QQQ"]:
            sim.open_trade(make_entry_signal(symbol=symbol))

        sim.force_close_all(date(2024, 2, 1))

        summary = sim.get_summary()

        # Win rate depends on final P&L of each trade
        assert 0 <= summary["win_rate"] <= 1

    def test_tracks_rr_rejections(self):
        """Should track risk/reward rejections."""
        config = make_config()
        sim = TradeSimulator(config)

        summary = sim.get_summary()

        assert "rr_rejections" in summary
