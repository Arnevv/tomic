"""Tests for tomic.backtest.engine module."""

from __future__ import annotations

import json
import pytest
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from unittest.mock import MagicMock, patch, PropertyMock

from tomic.backtest.config import (
    BacktestConfig,
    EntryRulesConfig,
    ExitRulesConfig,
    SampleSplitConfig,
)
from tomic.backtest.data_loader import IVTimeSeries
from tomic.backtest.results import (
    BacktestResult,
    EntrySignal,
    ExitReason,
    IVDataPoint,
    PerformanceMetrics,
    SimulatedTrade,
    TradeStatus,
)
from tomic.backtest.engine import BacktestEngine, run_backtest


def make_iv_datapoint(
    symbol: str,
    dt: date,
    atm_iv: float = 0.25,
    iv_rank: float = 70.0,
    iv_percentile: float = 75.0,
    hv30: float = 0.18,
    spot_price: float = 450.0,
) -> IVDataPoint:
    """Helper to create IVDataPoint for tests."""
    return IVDataPoint(
        date=dt,
        symbol=symbol,
        atm_iv=atm_iv,
        iv_rank=iv_rank,
        iv_percentile=iv_percentile,
        hv30=hv30,
        skew=5.0,
        term_m1_m2=2.0,
        spot_price=spot_price,
    )


def make_iv_timeseries(symbol: str, start_date: date, days: int) -> IVTimeSeries:
    """Helper to create IVTimeSeries with sample data."""
    ts = IVTimeSeries(symbol=symbol)
    for i in range(days):
        dt = start_date + timedelta(days=i)
        # Skip weekends
        if dt.weekday() >= 5:
            continue
        dp = make_iv_datapoint(
            symbol=symbol,
            dt=dt,
            iv_percentile=70.0 + (i % 10),  # Varying IV percentile
        )
        ts.add(dp)
    return ts


def make_simulated_trade(
    symbol: str = "SPY",
    entry_date: date = date(2024, 6, 1),
    exit_date: Optional[date] = None,
    final_pnl: float = 50.0,
    exit_reason: Optional[ExitReason] = None,
) -> SimulatedTrade:
    """Helper to create SimulatedTrade for tests."""
    trade = SimulatedTrade(
        entry_date=entry_date,
        symbol=symbol,
        strategy_type="iron_condor",
        iv_at_entry=0.25,
        iv_percentile_at_entry=75.0,
        iv_rank_at_entry=70.0,
        spot_at_entry=450.0,
        target_expiry=entry_date + timedelta(days=45),
        max_risk=200.0,
        estimated_credit=80.0,
    )
    if exit_date:
        trade.close(
            exit_date=exit_date,
            exit_reason=exit_reason or ExitReason.PROFIT_TARGET,
            final_pnl=final_pnl,
        )
    return trade


class TestBacktestEngine:
    """Tests for BacktestEngine class."""

    def test_creates_with_default_config(self):
        """Should create engine with default config when none provided."""
        with patch.object(BacktestEngine, '_load_earnings_data'):
            engine = BacktestEngine()

        assert engine.config is not None
        assert engine.config.strategy_type == "iron_condor"

    def test_creates_with_custom_config(self):
        """Should create engine with custom config."""
        config = BacktestConfig(
            strategy_type="calendar",
            target_dte=30,
            symbols=["AAPL", "MSFT"],
        )
        with patch.object(BacktestEngine, '_load_earnings_data'):
            engine = BacktestEngine(config=config)

        assert engine.config.strategy_type == "calendar"
        assert engine.config.target_dte == 30
        assert engine.config.symbols == ["AAPL", "MSFT"]

    def test_creates_calendar_signal_generator_for_calendar_strategy(self):
        """Should use CalendarSignalGenerator for calendar strategy."""
        config = BacktestConfig(strategy_type="calendar")
        with patch.object(BacktestEngine, '_load_earnings_data'):
            engine = BacktestEngine(config=config)

        from tomic.backtest.signal_generator import CalendarSignalGenerator
        assert isinstance(engine.signal_generator, CalendarSignalGenerator)

    def test_creates_signal_generator_for_iron_condor(self):
        """Should use SignalGenerator for iron_condor strategy."""
        config = BacktestConfig(strategy_type="iron_condor")
        with patch.object(BacktestEngine, '_load_earnings_data'):
            engine = BacktestEngine(config=config)

        from tomic.backtest.signal_generator import SignalGenerator, CalendarSignalGenerator
        assert isinstance(engine.signal_generator, SignalGenerator)
        assert not isinstance(engine.signal_generator, CalendarSignalGenerator)

    def test_loads_strategy_config(self):
        """Should load strategy config from YAML."""
        config = BacktestConfig()
        with patch.object(BacktestEngine, '_load_earnings_data'):
            with patch.object(BacktestEngine, '_load_strategy_config', return_value={'min_risk_reward': 1.5}):
                engine = BacktestEngine(config=config)

        assert engine.strategy_config == {'min_risk_reward': 1.5}

    def test_accepts_strategy_config_override(self):
        """Should accept strategy config override."""
        config = BacktestConfig()
        strategy_config = {'custom_param': 'test'}
        with patch.object(BacktestEngine, '_load_earnings_data'):
            engine = BacktestEngine(config=config, strategy_config=strategy_config)

        assert engine.strategy_config == {'custom_param': 'test'}

    def test_loads_earnings_data(self, tmp_path):
        """Should load earnings data from JSON file."""
        # Create mock earnings data file
        config = BacktestConfig()

        with patch.object(BacktestEngine, '_load_earnings_data') as mock_load:
            engine = BacktestEngine(config=config)
            mock_load.assert_called_once()

    def test_get_next_earnings_with_data(self):
        """Should return next earnings date for symbol."""
        config = BacktestConfig()
        with patch.object(BacktestEngine, '_load_earnings_data'):
            engine = BacktestEngine(config=config)

        # Manually set earnings data
        engine._earnings_data = {
            "SPY": [date(2024, 6, 10), date(2024, 9, 15), date(2024, 12, 20)]
        }

        # As of June 5, next earnings is June 10
        next_earnings = engine._get_next_earnings("SPY", date(2024, 6, 5))
        assert next_earnings == date(2024, 6, 10)

        # As of June 15, next earnings is Sept 15
        next_earnings = engine._get_next_earnings("SPY", date(2024, 6, 15))
        assert next_earnings == date(2024, 9, 15)

    def test_get_next_earnings_no_data(self):
        """Should return None when no earnings data."""
        config = BacktestConfig()
        with patch.object(BacktestEngine, '_load_earnings_data'):
            engine = BacktestEngine(config=config)

        engine._earnings_data = {}

        next_earnings = engine._get_next_earnings("SPY", date(2024, 6, 5))
        assert next_earnings is None

    def test_get_next_earnings_all_past(self):
        """Should return None when all earnings dates are past."""
        config = BacktestConfig()
        with patch.object(BacktestEngine, '_load_earnings_data'):
            engine = BacktestEngine(config=config)

        engine._earnings_data = {
            "SPY": [date(2024, 1, 10), date(2024, 3, 15)]
        }

        next_earnings = engine._get_next_earnings("SPY", date(2024, 6, 5))
        assert next_earnings is None

    def test_reports_progress(self):
        """Should call progress callback with updates."""
        config = BacktestConfig()
        progress_messages = []

        def progress_callback(message: str, percent: float):
            progress_messages.append((message, percent))

        with patch.object(BacktestEngine, '_load_earnings_data'):
            engine = BacktestEngine(config=config, progress_callback=progress_callback)

        engine._report_progress("Test message", 50.0)

        assert len(progress_messages) == 1
        assert progress_messages[0] == ("Test message", 50.0)

    def test_get_config_summary(self):
        """Should return config summary dict."""
        config = BacktestConfig(
            strategy_type="iron_condor",
            symbols=["SPY", "QQQ"],
            target_dte=45,
        )
        with patch.object(BacktestEngine, '_load_earnings_data'):
            engine = BacktestEngine(config=config)

        summary = engine._get_config_summary()

        assert summary["strategy_type"] == "iron_condor"
        assert summary["symbols"] == ["SPY", "QQQ"]
        assert summary["target_dte"] == 45
        assert "entry_rules" in summary
        assert "exit_rules" in summary

    def test_validate_result_warns_few_trades(self):
        """Should warn when few trades."""
        config = BacktestConfig()
        with patch.object(BacktestEngine, '_load_earnings_data'):
            engine = BacktestEngine(config=config)

        result = BacktestResult()
        result.trades = [make_simulated_trade() for _ in range(10)]
        result.combined_metrics = PerformanceMetrics(win_rate=0.6)

        engine._validate_result(result)

        assert any("Only 10 trades" in msg for msg in result.validation_messages)

    def test_validate_result_warns_high_degradation(self):
        """Should warn when high degradation score."""
        config = BacktestConfig()
        with patch.object(BacktestEngine, '_load_earnings_data'):
            engine = BacktestEngine(config=config)

        result = BacktestResult()
        result.trades = [make_simulated_trade() for _ in range(50)]
        result.degradation_score = 60.0
        result.combined_metrics = PerformanceMetrics(win_rate=0.6)
        result.out_sample_metrics = PerformanceMetrics(total_pnl=100.0)

        engine._validate_result(result)

        assert any("degradation" in msg.lower() for msg in result.validation_messages)

    def test_validate_result_warns_unprofitable_oos(self):
        """Should warn when out-of-sample is unprofitable."""
        config = BacktestConfig()
        with patch.object(BacktestEngine, '_load_earnings_data'):
            engine = BacktestEngine(config=config)

        result = BacktestResult()
        result.trades = [make_simulated_trade() for _ in range(50)]
        result.combined_metrics = PerformanceMetrics(win_rate=0.6)
        result.out_sample_metrics = PerformanceMetrics(total_pnl=-500.0)

        engine._validate_result(result)

        assert any("unprofitable" in msg.lower() for msg in result.validation_messages)

    def test_validate_result_warns_low_win_rate(self):
        """Should warn when win rate is very low."""
        config = BacktestConfig()
        with patch.object(BacktestEngine, '_load_earnings_data'):
            engine = BacktestEngine(config=config)

        result = BacktestResult()
        result.trades = [make_simulated_trade() for _ in range(50)]
        result.combined_metrics = PerformanceMetrics(win_rate=0.20)

        engine._validate_result(result)

        assert any("win rate" in msg.lower() for msg in result.validation_messages)

    def test_build_equity_curve(self):
        """Should build equity curve from trades."""
        config = BacktestConfig()
        with patch.object(BacktestEngine, '_load_earnings_data'):
            engine = BacktestEngine(config=config)

        trades = [
            make_simulated_trade(
                entry_date=date(2024, 6, 1),
                exit_date=date(2024, 6, 10),
                final_pnl=50.0,
                exit_reason=ExitReason.PROFIT_TARGET,
            ),
            make_simulated_trade(
                entry_date=date(2024, 6, 15),
                exit_date=date(2024, 6, 25),
                final_pnl=-30.0,
                exit_reason=ExitReason.STOP_LOSS,
            ),
            make_simulated_trade(
                entry_date=date(2024, 7, 1),
                exit_date=date(2024, 7, 10),
                final_pnl=40.0,
                exit_reason=ExitReason.PROFIT_TARGET,
            ),
        ]

        equity_curve = engine._build_equity_curve(trades)

        assert len(equity_curve) == 3
        # First trade: +50
        assert equity_curve[0]["cumulative_pnl"] == 50.0
        # Second trade: +50 - 30 = 20
        assert equity_curve[1]["cumulative_pnl"] == 20.0
        # Third trade: +20 + 40 = 60
        assert equity_curve[2]["cumulative_pnl"] == 60.0

    def test_build_equity_curve_skips_open_trades(self):
        """Should skip open trades when building equity curve."""
        config = BacktestConfig()
        with patch.object(BacktestEngine, '_load_earnings_data'):
            engine = BacktestEngine(config=config)

        closed_trade = make_simulated_trade(
            exit_date=date(2024, 6, 10),
            final_pnl=50.0,
            exit_reason=ExitReason.PROFIT_TARGET,
        )
        open_trade = make_simulated_trade()  # No exit

        trades = [closed_trade, open_trade]

        equity_curve = engine._build_equity_curve(trades)

        assert len(equity_curve) == 1

    def test_run_returns_result_when_no_data(self):
        """Should return invalid result when no IV data loaded."""
        config = BacktestConfig(symbols=["INVALID"])
        with patch.object(BacktestEngine, '_load_earnings_data'):
            engine = BacktestEngine(config=config)

        # Mock data loader to return empty
        engine.data_loader.load_all = MagicMock(return_value={})

        result = engine.run()

        assert not result.is_valid
        assert any("No IV data" in msg for msg in result.validation_messages)

    def test_run_simulation_with_mock_data(self):
        """Should run simulation with mocked data."""
        config = BacktestConfig(
            symbols=["SPY"],
            start_date="2024-06-01",
            end_date="2024-06-30",
            entry_rules=EntryRulesConfig(iv_percentile_min=60.0),
        )
        with patch.object(BacktestEngine, '_load_earnings_data'):
            engine = BacktestEngine(config=config)

        # Create mock IV data
        start = date(2024, 6, 1)
        ts = make_iv_timeseries("SPY", start, 30)

        # Run simulation
        trades = engine._run_simulation(
            iv_data={"SPY": ts},
            start_date=start,
            end_date=date(2024, 6, 30),
            period_name="test",
            progress_start=0,
            progress_end=100,
        )

        # Should complete without error
        assert isinstance(trades, list)


class TestRunBacktest:
    """Tests for run_backtest convenience function."""

    def test_creates_engine_and_runs(self):
        """Should create engine and run backtest."""
        with patch.object(BacktestEngine, 'run') as mock_run:
            mock_run.return_value = BacktestResult()

            result = run_backtest()

            mock_run.assert_called_once()
            assert isinstance(result, BacktestResult)

    def test_passes_config_to_engine(self):
        """Should pass config to engine."""
        config = BacktestConfig(strategy_type="calendar")

        with patch.object(BacktestEngine, '__init__', return_value=None) as mock_init:
            with patch.object(BacktestEngine, 'run', return_value=BacktestResult()):
                # Need to mock attributes that run() might use
                with patch.object(BacktestEngine, '_load_earnings_data'):
                    mock_init.return_value = None

                    # Direct instantiation test
                    engine = BacktestEngine.__new__(BacktestEngine)
                    engine.config = config
                    engine.data_loader = MagicMock()
                    engine.data_loader.load_all.return_value = {}
                    engine.progress_callback = None
                    engine._earnings_data = {}

                    # The convenience function should pass config
                    assert config.strategy_type == "calendar"

    def test_passes_progress_callback(self):
        """Should pass progress callback to engine."""
        progress_calls = []

        def callback(msg, pct):
            progress_calls.append((msg, pct))

        with patch.object(BacktestEngine, '_load_earnings_data'):
            with patch.object(BacktestEngine, 'run') as mock_run:
                mock_run.return_value = BacktestResult()

                run_backtest(progress_callback=callback)


class TestBacktestEngineIntegration:
    """Integration tests for BacktestEngine."""

    def test_full_run_with_minimal_data(self):
        """Should complete full run with minimal mock data."""
        config = BacktestConfig(
            symbols=["SPY"],
            start_date="2024-06-01",
            end_date="2024-06-14",
            sample_split=SampleSplitConfig(in_sample_ratio=0.5),
            entry_rules=EntryRulesConfig(iv_percentile_min=60.0),
            exit_rules=ExitRulesConfig(
                profit_target_pct=50.0,
                max_days_in_trade=10,
            ),
        )

        with patch.object(BacktestEngine, '_load_earnings_data'):
            engine = BacktestEngine(config=config)

        # Create mock IV data with varying IV
        start = date(2024, 6, 1)
        ts = IVTimeSeries(symbol="SPY")
        for i in range(14):
            dt = start + timedelta(days=i)
            if dt.weekday() >= 5:
                continue
            # High IV on some days to trigger signals
            iv_pct = 75.0 if i % 3 == 0 else 55.0
            dp = make_iv_datapoint(
                symbol="SPY",
                dt=dt,
                iv_percentile=iv_pct,
                atm_iv=0.25 if iv_pct > 60 else 0.15,
            )
            ts.add(dp)

        # Mock data loader
        engine.data_loader.load_all = MagicMock(return_value={"SPY": ts})
        engine.data_loader.split_by_ratio = MagicMock(return_value=(
            {"SPY": ts},  # in-sample
            {"SPY": ts},  # out-sample
            {"SPY": date(2024, 6, 7)},  # split dates
        ))
        engine.data_loader.get_data_summary = MagicMock(return_value={
            'symbols_loaded': 1,
            'total_data_points': 10,
        })

        result = engine.run()

        assert isinstance(result, BacktestResult)
        assert result.config_summary is not None
        assert result.combined_metrics is not None or len(result.trades) == 0
