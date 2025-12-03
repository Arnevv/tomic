"""Tests for tomic.backtest.results module."""

from __future__ import annotations

import pytest
from datetime import date, timedelta

from tomic.backtest.results import (
    TradeStatus,
    ExitReason,
    IVDataPoint,
    EntrySignal,
    SimulatedTrade,
    PerformanceMetrics,
    BacktestResult,
)


class TestTradeStatus:
    """Tests for TradeStatus enum."""

    def test_has_open_status(self):
        assert TradeStatus.OPEN.value == "open"

    def test_has_closed_status(self):
        assert TradeStatus.CLOSED.value == "closed"


class TestExitReason:
    """Tests for ExitReason enum."""

    def test_has_all_exit_reasons(self):
        assert ExitReason.PROFIT_TARGET.value == "profit_target"
        assert ExitReason.STOP_LOSS.value == "stop_loss"
        assert ExitReason.TIME_DECAY.value == "time_decay_dte"
        assert ExitReason.MAX_DIT.value == "max_days_in_trade"
        assert ExitReason.IV_COLLAPSE.value == "iv_collapse"
        assert ExitReason.DELTA_BREACH.value == "delta_breach"
        assert ExitReason.EXPIRATION.value == "expiration"
        assert ExitReason.MANUAL.value == "manual"


class TestIVDataPoint:
    """Tests for IVDataPoint dataclass."""

    def test_creates_from_dict(self):
        """Should create IVDataPoint from dictionary."""
        data = {
            "date": "2024-01-15",
            "atm_iv": 0.20,
            "iv_rank (IV)": 65.0,
            "iv_percentile (IV)": 70.0,
            "hv30": 0.18,
            "spot_price": 450.0,
        }

        dp = IVDataPoint.from_dict(data, "SPY")

        assert dp.date == date(2024, 1, 15)
        assert dp.symbol == "SPY"
        assert dp.atm_iv == 0.20
        assert dp.iv_rank == 65.0
        assert dp.iv_percentile == 70.0

    def test_handles_legacy_hv_fields(self):
        """Should support legacy HV field names."""
        data = {
            "date": "2024-01-15",
            "atm_iv": 0.20,
            "iv_rank (HV)": 60.0,
            "iv_percentile (HV)": 65.0,
        }

        dp = IVDataPoint.from_dict(data, "SPY")

        assert dp.iv_rank == 60.0
        assert dp.iv_percentile == 65.0

    def test_handles_close_as_spot(self):
        """Should use 'close' as fallback for spot_price."""
        data = {
            "date": "2024-01-15",
            "atm_iv": 0.20,
            "iv_percentile (IV)": 70.0,
            "close": 445.0,
        }

        dp = IVDataPoint.from_dict(data, "SPY")

        assert dp.spot_price == 445.0

    def test_is_valid_checks_required_fields(self):
        """is_valid should check date, atm_iv, iv_percentile."""
        valid = IVDataPoint(
            date=date(2024, 1, 15),
            symbol="SPY",
            atm_iv=0.20,
            iv_percentile=70.0,
        )
        invalid_no_date = IVDataPoint(
            date=None,
            symbol="SPY",
            atm_iv=0.20,
            iv_percentile=70.0,
        )
        invalid_no_iv = IVDataPoint(
            date=date(2024, 1, 15),
            symbol="SPY",
            atm_iv=None,
            iv_percentile=70.0,
        )

        assert valid.is_valid() is True
        assert invalid_no_date.is_valid() is False
        assert invalid_no_iv.is_valid() is False

    def test_handles_invalid_date_string(self):
        """Should handle invalid date strings gracefully."""
        data = {
            "date": "invalid-date",
            "atm_iv": 0.20,
            "iv_percentile (IV)": 70.0,
        }

        dp = IVDataPoint.from_dict(data, "SPY")

        assert dp.date is None


class TestSimulatedTrade:
    """Tests for SimulatedTrade dataclass."""

    def make_trade(self) -> SimulatedTrade:
        """Helper to create a test trade."""
        return SimulatedTrade(
            entry_date=date(2024, 1, 15),
            symbol="SPY",
            strategy_type="iron_condor",
            iv_at_entry=0.20,
            iv_percentile_at_entry=70.0,
            iv_rank_at_entry=65.0,
            spot_at_entry=450.0,
            target_expiry=date(2024, 3, 1),
            max_risk=200.0,
            estimated_credit=50.0,
        )

    def test_creates_with_open_status(self):
        """Should create with OPEN status by default."""
        trade = self.make_trade()

        assert trade.status == TradeStatus.OPEN

    def test_close_updates_all_fields(self):
        """close() should update all exit fields."""
        trade = self.make_trade()

        trade.close(
            exit_date=date(2024, 2, 1),
            exit_reason=ExitReason.PROFIT_TARGET,
            final_pnl=25.0,
            iv_at_exit=0.15,
            spot_at_exit=455.0,
        )

        assert trade.status == TradeStatus.CLOSED
        assert trade.exit_date == date(2024, 2, 1)
        assert trade.exit_reason == ExitReason.PROFIT_TARGET
        assert trade.final_pnl == 25.0
        assert trade.iv_at_exit == 0.15
        assert trade.spot_at_exit == 455.0

    def test_is_winner_checks_pnl(self):
        """is_winner() should return True for positive P&L."""
        winner = self.make_trade()
        winner.final_pnl = 50.0

        loser = self.make_trade()
        loser.final_pnl = -50.0

        assert winner.is_winner() is True
        assert loser.is_winner() is False

    def test_return_on_risk_calculation(self):
        """return_on_risk() should calculate P&L / max_risk."""
        trade = self.make_trade()
        trade.max_risk = 200.0
        trade.final_pnl = 50.0

        ror = trade.return_on_risk()

        assert ror == 0.25  # 50/200

    def test_return_on_risk_handles_zero_risk(self):
        """return_on_risk() should handle zero max_risk."""
        trade = self.make_trade()
        trade.max_risk = 0.0
        trade.final_pnl = 50.0

        ror = trade.return_on_risk()

        assert ror == 0.0


class TestBacktestResult:
    """Tests for BacktestResult dataclass."""

    def make_trade(
        self,
        entry_date: date,
        final_pnl: float = 50.0,
    ) -> SimulatedTrade:
        """Helper to create a test trade."""
        trade = SimulatedTrade(
            entry_date=entry_date,
            symbol="SPY",
            strategy_type="iron_condor",
            iv_at_entry=0.20,
            iv_percentile_at_entry=70.0,
            iv_rank_at_entry=65.0,
            spot_at_entry=450.0,
            target_expiry=entry_date + timedelta(days=45),
            max_risk=200.0,
            estimated_credit=50.0,
        )
        trade.final_pnl = final_pnl
        return trade

    def test_get_in_sample_trades(self):
        """Should filter trades by in-sample date."""
        result = BacktestResult(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            in_sample_end_date=date(2024, 6, 30),
            trades=[
                self.make_trade(date(2024, 3, 1)),  # In-sample
                self.make_trade(date(2024, 5, 1)),  # In-sample
                self.make_trade(date(2024, 8, 1)),  # Out-of-sample
            ],
        )

        in_sample = result.get_in_sample_trades()

        assert len(in_sample) == 2
        assert all(t.entry_date <= date(2024, 6, 30) for t in in_sample)

    def test_get_out_sample_trades(self):
        """Should filter trades by out-of-sample date."""
        result = BacktestResult(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            in_sample_end_date=date(2024, 6, 30),
            trades=[
                self.make_trade(date(2024, 3, 1)),  # In-sample
                self.make_trade(date(2024, 8, 1)),  # Out-of-sample
                self.make_trade(date(2024, 10, 1)),  # Out-of-sample
            ],
        )

        out_sample = result.get_out_sample_trades()

        assert len(out_sample) == 2
        assert all(t.entry_date > date(2024, 6, 30) for t in out_sample)

    def test_get_out_sample_returns_all_when_no_split(self):
        """Should return all trades when in_sample_end_date is None."""
        result = BacktestResult(
            in_sample_end_date=None,
            trades=[
                self.make_trade(date(2024, 3, 1)),
                self.make_trade(date(2024, 8, 1)),
            ],
        )

        out_sample = result.get_out_sample_trades()

        assert len(out_sample) == 2

    def test_summary_returns_dict(self):
        """summary() should return summary dict."""
        result = BacktestResult(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            trades=[self.make_trade(date(2024, 3, 1))],
            combined_metrics=PerformanceMetrics(
                total_pnl=100.0,
                win_rate=0.7,
                sharpe_ratio=1.5,
                max_drawdown=50.0,
            ),
        )

        summary = result.summary()

        assert summary["total_trades"] == 1
        assert "date_range" in summary
        assert "combined_metrics" in summary
        assert summary["combined_metrics"]["total_pnl"] == 100.0
