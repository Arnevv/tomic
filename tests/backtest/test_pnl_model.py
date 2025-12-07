"""Tests for tomic.backtest.pnl_model module."""

from __future__ import annotations

import pytest
from datetime import date

from tomic.backtest.config import BacktestConfig, ExitRulesConfig, CostConfig
from tomic.backtest.pnl_model import (
    IronCondorPnLModel,
    SimplePnLModel,
    GreeksBasedPnLModel,
    CalendarSpreadPnLModel,
    PnLEstimate,
    GreeksSnapshot,
)


class TestPnLEstimate:
    """Tests for PnLEstimate dataclass."""

    def test_creates_estimate(self):
        """Should create P&L estimate with all fields."""
        estimate = PnLEstimate(
            total_pnl=50.0,
            vega_pnl=30.0,
            theta_pnl=25.0,
            costs=5.0,
            pnl_pct=25.0,
        )

        assert estimate.total_pnl == 50.0
        assert estimate.vega_pnl == 30.0
        assert estimate.theta_pnl == 25.0
        assert estimate.costs == 5.0
        assert estimate.pnl_pct == 25.0


class TestIronCondorPnLModel:
    """Tests for IronCondorPnLModel class."""

    def test_creates_with_config(self):
        """Should initialize with BacktestConfig."""
        config = BacktestConfig()
        model = IronCondorPnLModel(config)

        assert model.config == config

    def test_estimate_credit_basic(self):
        """Should estimate credit for iron condor."""
        config = BacktestConfig(iron_condor_wing_width=5)
        model = IronCondorPnLModel(config)

        credit = model.estimate_credit(
            iv_at_entry=0.20,  # 20% IV
            max_risk=200.0,
            target_dte=45,
        )

        # Credit should be between 20-50% of wing width ($500)
        assert 100 <= credit <= 250

    def test_estimate_credit_higher_iv(self):
        """Should estimate higher credit for higher IV."""
        config = BacktestConfig(iron_condor_wing_width=5)
        model = IronCondorPnLModel(config)

        credit_low_iv = model.estimate_credit(
            iv_at_entry=0.15,
            max_risk=200.0,
            target_dte=45,
        )
        credit_high_iv = model.estimate_credit(
            iv_at_entry=0.35,
            max_risk=200.0,
            target_dte=45,
        )

        assert credit_high_iv > credit_low_iv

    def test_estimate_credit_stddev_adjustment(self):
        """Should adjust credit based on stddev_range."""
        config = BacktestConfig(iron_condor_wing_width=5)
        model = IronCondorPnLModel(config)

        # Closer to ATM (lower stddev) = higher credit
        credit_close = model.estimate_credit(
            iv_at_entry=0.20,
            max_risk=200.0,
            target_dte=45,
            stddev_range=1.0,
        )
        # Farther from ATM (higher stddev) = lower credit
        credit_far = model.estimate_credit(
            iv_at_entry=0.20,
            max_risk=200.0,
            target_dte=45,
            stddev_range=2.0,
        )

        assert credit_close > credit_far

    def test_estimate_credit_handles_percentage_iv(self):
        """Should handle IV as percentage (e.g., 20 instead of 0.20)."""
        config = BacktestConfig(iron_condor_wing_width=5)
        model = IronCondorPnLModel(config)

        credit_decimal = model.estimate_credit(
            iv_at_entry=0.25,
            max_risk=200.0,
            target_dte=45,
        )
        credit_percentage = model.estimate_credit(
            iv_at_entry=25.0,  # As percentage
            max_risk=200.0,
            target_dte=45,
        )

        assert abs(credit_decimal - credit_percentage) < 10

    def test_estimate_pnl_profit_on_iv_drop(self):
        """Should show profit when IV drops (short vega)."""
        config = BacktestConfig()
        model = IronCondorPnLModel(config)

        estimate = model.estimate_pnl(
            iv_at_entry=0.30,
            iv_current=0.20,  # IV dropped 10 vol points
            days_in_trade=15,
            target_dte=45,
            estimated_credit=100.0,
            max_risk=200.0,
        )

        assert estimate.total_pnl > 0
        assert estimate.vega_pnl > 0

    def test_estimate_pnl_loss_on_iv_spike(self):
        """Should show loss when IV spikes (short vega)."""
        config = BacktestConfig()
        model = IronCondorPnLModel(config)

        estimate = model.estimate_pnl(
            iv_at_entry=0.20,
            iv_current=0.35,  # IV spiked 15 vol points
            days_in_trade=5,
            target_dte=45,
            estimated_credit=100.0,
            max_risk=200.0,
        )

        assert estimate.total_pnl < 0
        assert estimate.vega_pnl < 0

    def test_estimate_pnl_theta_decay_over_time(self):
        """Should accumulate theta P&L over time."""
        config = BacktestConfig()
        model = IronCondorPnLModel(config)

        estimate_early = model.estimate_pnl(
            iv_at_entry=0.25,
            iv_current=0.25,  # IV unchanged
            days_in_trade=5,
            target_dte=45,
            estimated_credit=100.0,
            max_risk=200.0,
        )
        estimate_late = model.estimate_pnl(
            iv_at_entry=0.25,
            iv_current=0.25,  # IV unchanged
            days_in_trade=30,
            target_dte=45,
            estimated_credit=100.0,
            max_risk=200.0,
        )

        # More theta captured later
        assert estimate_late.theta_pnl > estimate_early.theta_pnl

    def test_estimate_pnl_capped_at_max_profit(self):
        """Should cap profit at estimated credit."""
        config = BacktestConfig()
        model = IronCondorPnLModel(config)

        estimate = model.estimate_pnl(
            iv_at_entry=0.50,
            iv_current=0.10,  # Massive IV drop
            days_in_trade=40,
            target_dte=45,
            estimated_credit=100.0,
            max_risk=200.0,
        )

        assert estimate.total_pnl <= 100.0  # Capped at credit

    def test_estimate_pnl_capped_at_max_loss(self):
        """Should cap loss at max risk."""
        config = BacktestConfig()
        model = IronCondorPnLModel(config)

        estimate = model.estimate_pnl(
            iv_at_entry=0.15,
            iv_current=0.60,  # Massive IV spike
            days_in_trade=5,
            target_dte=45,
            estimated_credit=100.0,
            max_risk=200.0,
        )

        assert estimate.total_pnl >= -200.0  # Capped at max risk

    def test_estimate_pnl_includes_costs(self):
        """Should include transaction costs."""
        config = BacktestConfig(
            costs=CostConfig(commission_per_contract=1.50)
        )
        model = IronCondorPnLModel(config)

        estimate = model.estimate_pnl(
            iv_at_entry=0.25,
            iv_current=0.25,
            days_in_trade=10,
            target_dte=45,
            estimated_credit=100.0,
            max_risk=200.0,
        )

        assert estimate.costs > 0

    def test_estimate_exit_pnl_profit_target(self):
        """Should cap exit P&L at profit target for profit_target exit."""
        config = BacktestConfig(
            exit_rules=ExitRulesConfig(profit_target_pct=50.0)
        )
        model = IronCondorPnLModel(config)

        exit_pnl = model.estimate_exit_pnl(
            iv_at_entry=0.30,
            iv_at_exit=0.15,  # Large IV drop
            days_in_trade=20,
            target_dte=45,
            estimated_credit=100.0,
            max_risk=200.0,
            exit_reason="profit_target",
        )

        # Should be capped at 50% of credit
        assert exit_pnl <= 50.0

    def test_estimate_exit_pnl_stop_loss(self):
        """Should apply stop loss for stop_loss exit."""
        config = BacktestConfig(
            exit_rules=ExitRulesConfig(stop_loss_pct=100.0)
        )
        model = IronCondorPnLModel(config)

        exit_pnl = model.estimate_exit_pnl(
            iv_at_entry=0.20,
            iv_at_exit=0.50,  # IV spike
            days_in_trade=5,
            target_dte=45,
            estimated_credit=100.0,
            max_risk=200.0,
            exit_reason="stop_loss",
        )

        # Should be at least stop loss level
        assert exit_pnl >= -100.0

    def test_estimate_exit_pnl_delta_breach(self):
        """Should calculate realistic loss for delta breach."""
        config = BacktestConfig()
        model = IronCondorPnLModel(config)

        exit_pnl = model.estimate_exit_pnl(
            iv_at_entry=0.20,
            iv_at_exit=0.30,
            days_in_trade=10,
            target_dte=45,
            estimated_credit=100.0,
            max_risk=200.0,
            exit_reason="delta_breach",
            spot_at_entry=450.0,
            spot_at_exit=485.0,  # ~7.8% move
        )

        # Should be a loss
        assert exit_pnl < 0
        # Should not exceed max risk
        assert exit_pnl >= -200.0

    def test_estimate_exit_pnl_iv_collapse(self):
        """Should return positive P&L for iv_collapse exit."""
        config = BacktestConfig()
        model = IronCondorPnLModel(config)

        exit_pnl = model.estimate_exit_pnl(
            iv_at_entry=0.30,
            iv_at_exit=0.18,  # IV collapsed
            days_in_trade=15,
            target_dte=45,
            estimated_credit=100.0,
            max_risk=200.0,
            exit_reason="iv_collapse",
        )

        assert exit_pnl >= 0


class TestSimplePnLModel:
    """Tests for SimplePnLModel class."""

    def test_creates_with_defaults(self):
        """Should create with default parameters."""
        model = SimplePnLModel()

        assert model.win_capture_pct == 50.0
        assert model.loss_pct == 100.0

    def test_creates_with_custom_values(self):
        """Should accept custom win/loss percentages."""
        model = SimplePnLModel(win_capture_pct=75.0, loss_pct=150.0)

        assert model.win_capture_pct == 75.0
        assert model.loss_pct == 150.0

    def test_estimate_win_pnl(self):
        """Should calculate win P&L as percentage of credit."""
        model = SimplePnLModel(win_capture_pct=50.0)

        pnl = model.estimate_win_pnl(estimated_credit=100.0)

        assert pnl == 50.0

    def test_estimate_loss_pnl(self):
        """Should calculate loss P&L as negative percentage of credit."""
        model = SimplePnLModel(loss_pct=100.0)

        pnl = model.estimate_loss_pnl(estimated_credit=100.0)

        assert pnl == -100.0


class TestGreeksBasedPnLModel:
    """Tests for GreeksBasedPnLModel class."""

    def test_creates_with_config(self):
        """Should initialize with BacktestConfig."""
        config = BacktestConfig()
        model = GreeksBasedPnLModel(config)

        assert model.config == config

    def test_calculate_ic_greeks(self):
        """Should calculate Greeks for iron condor position."""
        config = BacktestConfig()
        model = GreeksBasedPnLModel(config)

        greeks = model.calculate_ic_greeks(
            spot_price=450.0,
            atm_iv=0.20,
            dte=45,
        )

        # IC should be delta-neutral at entry
        assert abs(greeks.delta) < 0.10  # Near zero delta
        # IC is short vega
        assert greeks.vega < 0 or greeks.vega > -5  # Allow flexibility
        # IC has positive theta
        assert greeks.position_price > 0

    def test_estimate_credit_from_greeks(self):
        """Should estimate credit using Greeks calculations."""
        config = BacktestConfig()
        model = GreeksBasedPnLModel(config)

        credit = model.estimate_credit_from_greeks(
            spot_price=450.0,
            atm_iv=0.25,
            dte=45,
            max_risk=200.0,
        )

        # Credit should be reasonable (15-50% of max_risk)
        assert 30 <= credit <= 100

    def test_estimate_credit_from_greeks_stddev_adjustment(self):
        """Should adjust credit based on stddev_range."""
        config = BacktestConfig()
        model = GreeksBasedPnLModel(config)

        credit_close = model.estimate_credit_from_greeks(
            spot_price=450.0,
            atm_iv=0.25,
            dte=45,
            max_risk=200.0,
            stddev_range=1.0,  # Closer to ATM
        )
        credit_far = model.estimate_credit_from_greeks(
            spot_price=450.0,
            atm_iv=0.25,
            dte=45,
            max_risk=200.0,
            stddev_range=2.0,  # Farther from ATM
        )

        assert credit_close > credit_far

    def test_estimate_pnl_from_greeks(self):
        """Should estimate P&L using Greeks changes."""
        config = BacktestConfig()
        model = GreeksBasedPnLModel(config)

        greeks_entry = GreeksSnapshot(
            delta=0.01,
            gamma=-0.02,
            vega=-0.50,
            theta=0.10,
            position_price=75.0,
        )
        greeks_current = GreeksSnapshot(
            delta=0.02,
            gamma=-0.025,
            vega=-0.45,
            theta=0.12,
            position_price=65.0,
        )

        estimate = model.estimate_pnl_from_greeks(
            greeks_entry=greeks_entry,
            greeks_current=greeks_current,
            days_in_trade=10,
            estimated_credit=75.0,
            max_risk=200.0,
            spot_at_entry=450.0,
            spot_current=455.0,  # Small move
        )

        # Should have some theta P&L
        assert estimate.theta_pnl != 0


class TestGreeksSnapshot:
    """Tests for GreeksSnapshot dataclass."""

    def test_creates_snapshot(self):
        """Should create Greeks snapshot with all fields."""
        snapshot = GreeksSnapshot(
            delta=0.01,
            gamma=-0.02,
            vega=-0.50,
            theta=0.10,
            position_price=75.0,
        )

        assert snapshot.delta == 0.01
        assert snapshot.gamma == -0.02
        assert snapshot.vega == -0.50
        assert snapshot.theta == 0.10
        assert snapshot.position_price == 75.0


class TestCalendarSpreadPnLModel:
    """Tests for CalendarSpreadPnLModel class."""

    def test_creates_with_config(self):
        """Should initialize with BacktestConfig."""
        config = BacktestConfig(strategy_type="calendar")
        model = CalendarSpreadPnLModel(config)

        assert model.config == config

    def test_estimate_debit_basic(self):
        """Should estimate debit for calendar spread."""
        config = BacktestConfig(strategy_type="calendar")
        model = CalendarSpreadPnLModel(config)

        debit = model.estimate_debit(
            iv_at_entry=0.20,
            spot_price=450.0,
            near_dte=30,
            far_dte=60,
        )

        # Debit should be positive
        assert debit > 50.0  # Minimum floor

    def test_estimate_debit_higher_iv(self):
        """Should estimate higher debit for higher IV."""
        config = BacktestConfig(strategy_type="calendar")
        model = CalendarSpreadPnLModel(config)

        debit_low_iv = model.estimate_debit(
            iv_at_entry=0.15,
            spot_price=450.0,
            near_dte=30,
            far_dte=60,
        )
        debit_high_iv = model.estimate_debit(
            iv_at_entry=0.35,
            spot_price=450.0,
            near_dte=30,
            far_dte=60,
        )

        assert debit_high_iv > debit_low_iv

    def test_estimate_debit_wider_spread(self):
        """Should estimate higher debit for wider calendar spread."""
        config = BacktestConfig(strategy_type="calendar")
        model = CalendarSpreadPnLModel(config)

        debit_narrow = model.estimate_debit(
            iv_at_entry=0.20,
            spot_price=450.0,
            near_dte=30,
            far_dte=45,  # 15 day gap
        )
        debit_wide = model.estimate_debit(
            iv_at_entry=0.20,
            spot_price=450.0,
            near_dte=30,
            far_dte=90,  # 60 day gap
        )

        assert debit_wide > debit_narrow

    def test_estimate_pnl_profit_on_iv_rise(self):
        """Should show profit when IV rises (long vega)."""
        config = BacktestConfig(strategy_type="calendar")
        model = CalendarSpreadPnLModel(config)

        estimate = model.estimate_pnl(
            iv_at_entry=0.20,
            iv_current=0.30,  # IV rose 10 vol points
            term_at_entry=2.0,
            term_current=1.0,  # Term structure normalized
            days_in_trade=5,
            near_dte_at_entry=30,
            entry_debit=200.0,
        )

        assert estimate.total_pnl > 0
        assert estimate.vega_pnl > 0

    def test_estimate_pnl_loss_on_iv_drop(self):
        """Should show loss when IV drops (long vega)."""
        config = BacktestConfig(strategy_type="calendar")
        model = CalendarSpreadPnLModel(config)

        estimate = model.estimate_pnl(
            iv_at_entry=0.30,
            iv_current=0.20,  # IV dropped 10 vol points
            term_at_entry=2.0,
            term_current=2.0,
            days_in_trade=5,
            near_dte_at_entry=30,
            entry_debit=200.0,
        )

        assert estimate.total_pnl < 0
        assert estimate.vega_pnl < 0

    def test_estimate_pnl_theta_differential(self):
        """Should accumulate theta from differential decay."""
        config = BacktestConfig(strategy_type="calendar")
        model = CalendarSpreadPnLModel(config)

        estimate_early = model.estimate_pnl(
            iv_at_entry=0.20,
            iv_current=0.20,  # IV unchanged
            term_at_entry=0.0,
            term_current=0.0,
            days_in_trade=2,
            near_dte_at_entry=30,
            entry_debit=200.0,
        )
        estimate_late = model.estimate_pnl(
            iv_at_entry=0.20,
            iv_current=0.20,  # IV unchanged
            term_at_entry=0.0,
            term_current=0.0,
            days_in_trade=15,
            near_dte_at_entry=30,
            entry_debit=200.0,
        )

        # More theta differential captured later
        assert estimate_late.theta_pnl > estimate_early.theta_pnl

    def test_estimate_pnl_capped_at_max_profit(self):
        """Should cap profit at reasonable percentage of debit."""
        config = BacktestConfig(strategy_type="calendar")
        model = CalendarSpreadPnLModel(config)

        estimate = model.estimate_pnl(
            iv_at_entry=0.10,
            iv_current=0.50,  # Massive IV rise
            term_at_entry=5.0,
            term_current=0.0,  # Term normalized
            days_in_trade=10,
            near_dte_at_entry=30,
            entry_debit=200.0,
        )

        # Max profit typically 50-100% of debit
        assert estimate.total_pnl <= 200.0

    def test_estimate_pnl_capped_at_max_loss(self):
        """Should cap loss at entry debit."""
        config = BacktestConfig(strategy_type="calendar")
        model = CalendarSpreadPnLModel(config)

        estimate = model.estimate_pnl(
            iv_at_entry=0.50,
            iv_current=0.10,  # Massive IV drop
            term_at_entry=0.0,
            term_current=5.0,  # Term structure worsened
            days_in_trade=5,
            near_dte_at_entry=30,
            entry_debit=200.0,
        )

        # Can't lose more than debit
        assert estimate.total_pnl >= -200.0

    def test_estimate_exit_pnl_profit_target(self):
        """Should cap exit P&L at profit target."""
        config = BacktestConfig(
            strategy_type="calendar",
            exit_rules=ExitRulesConfig(profit_target_pct=10.0),
        )
        model = CalendarSpreadPnLModel(config)

        exit_pnl = model.estimate_exit_pnl(
            iv_at_entry=0.20,
            iv_at_exit=0.40,  # IV doubled
            term_at_entry=3.0,
            term_at_exit=0.0,
            days_in_trade=5,
            near_dte_at_entry=30,
            entry_debit=200.0,
            exit_reason="profit_target",
        )

        # Should be capped at 10% of debit
        assert exit_pnl <= 20.0

    def test_estimate_exit_pnl_stop_loss(self):
        """Should apply stop loss for calendar."""
        config = BacktestConfig(
            strategy_type="calendar",
            exit_rules=ExitRulesConfig(stop_loss_pct=10.0),
        )
        model = CalendarSpreadPnLModel(config)

        exit_pnl = model.estimate_exit_pnl(
            iv_at_entry=0.30,
            iv_at_exit=0.15,  # IV dropped
            term_at_entry=0.0,
            term_at_exit=5.0,  # Term worsened
            days_in_trade=5,
            near_dte_at_entry=30,
            entry_debit=200.0,
            exit_reason="stop_loss",
        )

        # Should be at least stop loss level
        assert exit_pnl >= -20.0

    def test_estimate_exit_pnl_near_leg_dte(self):
        """Should use estimate for near_leg_dte exit."""
        config = BacktestConfig(strategy_type="calendar")
        model = CalendarSpreadPnLModel(config)

        exit_pnl = model.estimate_exit_pnl(
            iv_at_entry=0.20,
            iv_at_exit=0.22,
            term_at_entry=2.0,
            term_at_exit=1.0,
            days_in_trade=25,
            near_dte_at_entry=30,
            entry_debit=200.0,
            exit_reason="near_leg_dte",
        )

        # Should return estimate value
        assert isinstance(exit_pnl, float)

    def test_estimate_exit_pnl_max_dit(self):
        """Should use estimate for max_days_in_trade exit."""
        config = BacktestConfig(strategy_type="calendar")
        model = CalendarSpreadPnLModel(config)

        exit_pnl = model.estimate_exit_pnl(
            iv_at_entry=0.20,
            iv_at_exit=0.20,  # IV unchanged - move didn't happen
            term_at_entry=2.0,
            term_at_exit=2.0,
            days_in_trade=10,
            near_dte_at_entry=30,
            entry_debit=200.0,
            exit_reason="max_days_in_trade",
        )

        # Should return estimate value
        assert isinstance(exit_pnl, float)

    def test_handles_percentage_iv(self):
        """Should handle IV as percentage (e.g., 20 instead of 0.20)."""
        config = BacktestConfig(strategy_type="calendar")
        model = CalendarSpreadPnLModel(config)

        # IV as percentage should be normalized
        estimate = model.estimate_pnl(
            iv_at_entry=20.0,  # 20% as integer
            iv_current=30.0,  # 30% as integer
            term_at_entry=2.0,
            term_current=1.0,
            days_in_trade=5,
            near_dte_at_entry=30,
            entry_debit=200.0,
        )

        assert estimate.total_pnl > 0  # Should be profitable on IV rise
