"""Tests for tomic.backtest.config module."""

from __future__ import annotations

import pytest
import json
from datetime import date
from pathlib import Path

from tomic.backtest.config import (
    BacktestConfig,
    EntryRulesConfig,
    ExitRulesConfig,
    PositionSizingConfig,
    SampleSplitConfig,
    CostConfig,
    load_backtest_config,
    save_backtest_config,
)


class TestBacktestConfig:
    """Tests for BacktestConfig model."""

    def test_creates_with_defaults(self):
        """Should create config with default values."""
        config = BacktestConfig()

        assert config.strategy_type == "iron_condor"
        assert config.target_dte == 45
        assert len(config.symbols) == 5

    def test_creates_with_custom_values(self):
        """Should accept custom values."""
        config = BacktestConfig(
            strategy_type="calendar",
            target_dte=30,
            symbols=["AAPL", "MSFT"],
        )

        assert config.strategy_type == "calendar"
        assert config.target_dte == 30
        assert config.symbols == ["AAPL", "MSFT"]

    def test_get_in_sample_end_date(self):
        """Should calculate in-sample end date correctly."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-12-31",
            sample_split=SampleSplitConfig(in_sample_ratio=0.30),
        )

        end_date = config.get_in_sample_end_date()
        total_days = (date(2024, 12, 31) - date(2024, 1, 1)).days
        expected_days = int(total_days * 0.30)

        assert end_date == date(2024, 1, 1) + __import__('datetime').timedelta(days=expected_days)

    def test_get_out_sample_start_date(self):
        """Should return day after in-sample end."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        in_sample_end = config.get_in_sample_end_date()
        out_sample_start = config.get_out_sample_start_date()

        assert out_sample_start == in_sample_end + __import__('datetime').timedelta(days=1)


class TestEntryRulesConfig:
    """Tests for EntryRulesConfig model."""

    def test_creates_with_defaults(self):
        """Should create with default IV percentile."""
        config = EntryRulesConfig()

        assert config.iv_percentile_min == 60.0

    def test_allows_optional_fields(self):
        """Should allow optional fields to be None."""
        config = EntryRulesConfig(
            iv_percentile_min=50.0,
            iv_rank_min=None,
            skew_min=None,
        )

        assert config.iv_rank_min is None
        assert config.skew_min is None


class TestExitRulesConfig:
    """Tests for ExitRulesConfig model."""

    def test_creates_with_defaults(self):
        """Should create with TOMIC defaults."""
        config = ExitRulesConfig()

        assert config.profit_target_pct == 50.0
        assert config.stop_loss_pct == 100.0
        assert config.min_dte == 5
        assert config.max_days_in_trade == 45

    def test_accepts_custom_values(self):
        """Should accept custom exit rules."""
        config = ExitRulesConfig(
            profit_target_pct=75.0,
            stop_loss_pct=150.0,
            min_dte=7,
        )

        assert config.profit_target_pct == 75.0
        assert config.stop_loss_pct == 150.0
        assert config.min_dte == 7


class TestPositionSizingConfig:
    """Tests for PositionSizingConfig model."""

    def test_creates_with_defaults(self):
        """Should create with fixed risk defaults."""
        config = PositionSizingConfig()

        assert config.type == "fixed_risk"
        assert config.max_risk_per_trade == 200.0
        assert config.max_total_positions == 10

    def test_accepts_custom_sizing(self):
        """Should accept custom position sizing."""
        config = PositionSizingConfig(
            type="percent_equity",
            max_risk_per_trade=500.0,
            max_total_positions=5,
        )

        assert config.max_risk_per_trade == 500.0
        assert config.max_total_positions == 5


class TestCostConfig:
    """Tests for CostConfig model."""

    def test_creates_with_defaults(self):
        """Should create with default cost assumptions."""
        config = CostConfig()

        assert config.commission_per_contract == 1.0
        assert config.slippage_pct == 5.0


class TestLoadBacktestConfig:
    """Tests for load_backtest_config function."""

    def test_returns_default_when_file_missing(self, tmp_path):
        """Should return default config when file doesn't exist."""
        config = load_backtest_config(tmp_path / "nonexistent.yaml")

        assert config.strategy_type == "iron_condor"

    def test_loads_from_yaml_file(self, tmp_path):
        """Should load config from YAML file."""
        yaml_content = """
version: 1
strategy_type: calendar
target_dte: 30
symbols:
  - AAPL
  - MSFT
"""
        yaml_file = tmp_path / "backtest.yaml"
        yaml_file.write_text(yaml_content)

        config = load_backtest_config(yaml_file)

        assert config.strategy_type == "calendar"
        assert config.target_dte == 30
        assert config.symbols == ["AAPL", "MSFT"]


class TestSaveBacktestConfig:
    """Tests for save_backtest_config function."""

    def test_saves_to_yaml_file(self, tmp_path):
        """Should save config to YAML file."""
        config = BacktestConfig(
            strategy_type="test_strategy",
            target_dte=60,
        )
        yaml_file = tmp_path / "output.yaml"

        save_backtest_config(config, yaml_file)

        assert yaml_file.exists()
        content = yaml_file.read_text()
        assert "test_strategy" in content
        assert "60" in content

    def test_creates_parent_directories(self, tmp_path):
        """Should create parent directories if needed."""
        config = BacktestConfig()
        yaml_file = tmp_path / "subdir" / "output.yaml"

        save_backtest_config(config, yaml_file)

        assert yaml_file.exists()

    def test_roundtrip_preserves_values(self, tmp_path):
        """Should preserve values when saving and loading."""
        original = BacktestConfig(
            strategy_type="roundtrip_test",
            target_dte=42,
            symbols=["TEST"],
        )
        yaml_file = tmp_path / "roundtrip.yaml"

        save_backtest_config(original, yaml_file)
        loaded = load_backtest_config(yaml_file)

        assert loaded.strategy_type == original.strategy_type
        assert loaded.target_dte == original.target_dte
        assert loaded.symbols == original.symbols
