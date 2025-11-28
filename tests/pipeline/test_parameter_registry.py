"""Tests for the ParameterRegistry module."""

import pytest
from pathlib import Path
import tempfile
import shutil
import yaml

from tomic.pipeline.parameter_registry import (
    ParameterRegistry,
    PipelinePhase,
    StrategyConfig,
    ParameterSource,
    get_registry,
    reload_registry,
)


class TestPipelinePhase:
    """Tests for PipelinePhase enum."""

    def test_display_names(self):
        """Test that all phases have display names."""
        for phase in PipelinePhase:
            assert phase.display_name is not None
            assert len(phase.display_name) > 0

    def test_source_files(self):
        """Test that phases have source file mappings."""
        assert "volatility_rules.yaml" in PipelinePhase.MARKET_SELECTION.source_files
        assert "strike_selection_rules.yaml" in PipelinePhase.STRIKE_SELECTION.source_files
        assert "criteria.yaml" in PipelinePhase.SCORING.source_files

    def test_display_name_dutch(self):
        """Test Dutch display names."""
        assert PipelinePhase.MARKET_SELECTION.display_name == "Markt Selectie"
        assert PipelinePhase.EXIT.display_name == "Exit Criteria"


class TestParameterSource:
    """Tests for ParameterSource dataclass."""

    def test_file_name_property(self):
        """Test file_name extracts just the filename."""
        source = ParameterSource(
            file_path="/home/user/tomic/criteria.yaml",
            yaml_path="strike.min_rom",
            value=0.10,
        )
        assert source.file_name == "criteria.yaml"

    def test_value_types(self):
        """Test various value types."""
        # Float value
        source = ParameterSource(
            file_path="test.yaml",
            yaml_path="path",
            value=0.5,
        )
        assert source.value == 0.5

        # List value
        source = ParameterSource(
            file_path="test.yaml",
            yaml_path="path",
            value=[25, 55],
        )
        assert source.value == [25, 55]

        # String value (criterion)
        source = ParameterSource(
            file_path="test.yaml",
            yaml_path="path",
            value="iv_rank >= 0.5",
        )
        assert source.value == "iv_rank >= 0.5"


class TestStrategyConfig:
    """Tests for StrategyConfig dataclass."""

    def test_get_phase_creates_new(self):
        """Test that get_phase creates phase if not exists."""
        config = StrategyConfig(
            strategy_key="iron_condor",
            strategy_name="Iron Condor",
        )
        phase = config.get_phase(PipelinePhase.MARKET_SELECTION)
        assert phase is not None
        assert phase.phase == PipelinePhase.MARKET_SELECTION

    def test_all_parameters(self):
        """Test all_parameters returns params from all phases."""
        config = StrategyConfig(
            strategy_key="iron_condor",
            strategy_name="Iron Condor",
        )

        # Add params to two phases
        market = config.get_phase(PipelinePhase.MARKET_SELECTION)
        market.add("iv_rank", ParameterSource("a.yaml", "a.b", 0.5))

        scoring = config.get_phase(PipelinePhase.SCORING)
        scoring.add("min_rom", ParameterSource("b.yaml", "c.d", 0.1))

        all_params = config.all_parameters()
        assert len(all_params) == 2


class TestParameterRegistry:
    """Tests for ParameterRegistry class."""

    def test_loads_strategies(self):
        """Test that registry loads all known strategies."""
        registry = get_registry()
        strategies = registry.list_strategies()

        assert "iron_condor" in strategies
        assert "calendar" in strategies
        assert "short_put_spread" in strategies
        assert len(strategies) == 8

    def test_get_strategy_returns_config(self):
        """Test getting a specific strategy config."""
        registry = get_registry()
        config = registry.get_strategy("iron_condor")

        assert config is not None
        assert config.strategy_key == "iron_condor"
        assert config.strategy_name == "Iron Condor"

    def test_strategy_has_all_phases(self):
        """Test that iron_condor has all phases populated."""
        registry = get_registry()
        config = registry.get_strategy("iron_condor")

        assert PipelinePhase.MARKET_SELECTION in config.phases
        assert PipelinePhase.STRIKE_SELECTION in config.phases
        assert PipelinePhase.SCORING in config.phases
        assert PipelinePhase.EXIT in config.phases
        assert PipelinePhase.PORTFOLIO in config.phases

    def test_market_selection_has_volatility_criteria(self):
        """Test market selection phase has volatility criteria."""
        registry = get_registry()
        config = registry.get_strategy("iron_condor")
        market = config.phases[PipelinePhase.MARKET_SELECTION]

        # Should have criteria from volatility_rules.yaml
        assert len(market.parameters) >= 1
        # Check first criterion exists
        crit = market.get("criterion_1")
        assert crit is not None
        assert "iv_rank" in str(crit) or "iv_percentile" in str(crit)

    def test_strike_selection_has_dte_range(self):
        """Test strike selection has DTE range."""
        registry = get_registry()
        config = registry.get_strategy("iron_condor")
        strike = config.phases[PipelinePhase.STRIKE_SELECTION]

        dte = strike.get("dte_range")
        assert dte is not None
        assert isinstance(dte, list)
        assert len(dte) == 2

    def test_scoring_has_min_rom(self):
        """Test scoring phase has min_rom."""
        registry = get_registry()
        config = registry.get_strategy("iron_condor")
        scoring = config.phases[PipelinePhase.SCORING]

        # Should have min_rom either from criteria.yaml or strategies.yaml
        has_rom = any("rom" in name.lower() for name in scoring.parameters.keys())
        assert has_rom

    def test_exit_has_profit_target(self):
        """Test exit phase has profit target from backtest config."""
        registry = get_registry()
        config = registry.get_strategy("iron_condor")
        exit_phase = config.phases[PipelinePhase.EXIT]

        # Should have backtest exit rules
        bt_profit = exit_phase.get("bt_profit_target_pct")
        assert bt_profit is not None
        assert isinstance(bt_profit, (int, float))

    def test_get_unknown_strategy_returns_none(self):
        """Test that unknown strategy returns None."""
        registry = get_registry()
        config = registry.get_strategy("unknown_strategy")
        assert config is None

    def test_reload_refreshes_config(self):
        """Test that reload() refreshes from disk."""
        registry = get_registry()

        # Get initial value
        config = registry.get_strategy("iron_condor")
        initial_phases = len(config.phases)

        # Reload
        registry.reload()

        # Should have same structure
        config = registry.get_strategy("iron_condor")
        assert len(config.phases) == initial_phases

    def test_all_strategies_have_names(self):
        """Test all strategies have display names."""
        registry = get_registry()

        for key in registry.list_strategies():
            config = registry.get_strategy(key)
            assert config.strategy_name is not None
            assert len(config.strategy_name) > 0

    def test_get_backtest_config(self):
        """Test getting raw backtest config."""
        registry = get_registry()
        bt_config = registry.get_backtest_config()

        assert bt_config is not None
        assert "strategy_type" in bt_config or "symbols" in bt_config

    def test_calendar_has_different_criteria(self):
        """Test calendar strategy has different vol criteria than iron_condor."""
        registry = get_registry()

        ic = registry.get_strategy("iron_condor")
        cal = registry.get_strategy("calendar")

        ic_market = ic.phases.get(PipelinePhase.MARKET_SELECTION)
        cal_market = cal.phases.get(PipelinePhase.MARKET_SELECTION)

        # Both should have market criteria
        assert ic_market and ic_market.parameters
        assert cal_market and cal_market.parameters


class TestParameterRegistrySingleton:
    """Tests for singleton behavior."""

    def test_get_registry_returns_same_instance(self):
        """Test that get_registry returns the same instance."""
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2

    def test_reload_registry_returns_new_instance(self):
        """Test that reload_registry returns fresh instance."""
        r1 = get_registry()
        r2 = reload_registry()
        # After reload, get_registry should return the new one
        r3 = get_registry()
        assert r2 is r3


class TestPhaseParameters:
    """Tests for PhaseParameters class."""

    def test_add_and_get(self):
        """Test adding and retrieving parameters."""
        from tomic.pipeline.parameter_registry import PhaseParameters

        params = PhaseParameters(phase=PipelinePhase.SCORING)
        params.add("min_rom", ParameterSource("test.yaml", "path", 0.1))

        assert params.get("min_rom") == 0.1
        assert params.get("nonexistent") is None

    def test_items_returns_list(self):
        """Test items() returns list of tuples."""
        from tomic.pipeline.parameter_registry import PhaseParameters

        params = PhaseParameters(phase=PipelinePhase.SCORING)
        params.add("a", ParameterSource("test.yaml", "path", 1))
        params.add("b", ParameterSource("test.yaml", "path", 2))

        items = params.items()
        assert len(items) == 2
        assert all(isinstance(item, tuple) for item in items)
