"""Parameter Registry for unified pipeline configuration.

Consolidates all pipeline parameters from multiple YAML files into
a single view, organized by strategy and pipeline phase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import yaml

from tomic.logutils import logger


class PipelinePhase(str, Enum):
    """Phases in the trading pipeline."""
    MARKET_SELECTION = "market_selection"      # volatility_rules.yaml
    STRIKE_SELECTION = "strike_selection"      # strike_selection_rules.yaml
    SCORING = "scoring"                        # criteria.yaml + strategies.yaml
    EXIT = "exit"                              # criteria.yaml + backtest.yaml
    PORTFOLIO = "portfolio"                    # criteria.yaml portfolio section

    @property
    def display_name(self) -> str:
        """Human-readable name for the phase."""
        names = {
            self.MARKET_SELECTION: "Markt Selectie",
            self.STRIKE_SELECTION: "Strike Selectie",
            self.SCORING: "Scoring & Filtering",
            self.EXIT: "Exit Criteria",
            self.PORTFOLIO: "Portfolio Gates",
        }
        return names.get(self, self.value)

    @property
    def source_files(self) -> List[str]:
        """Config files that contribute to this phase."""
        files = {
            self.MARKET_SELECTION: ["volatility_rules.yaml"],
            self.STRIKE_SELECTION: ["strike_selection_rules.yaml"],
            self.SCORING: ["criteria.yaml", "config/strategies.yaml"],
            self.EXIT: ["criteria.yaml", "config/backtest.yaml"],
            self.PORTFOLIO: ["criteria.yaml"],
        }
        return files.get(self, [])


@dataclass
class ParameterSource:
    """Tracks where a parameter comes from."""
    file_path: str
    yaml_path: str  # e.g., "strike.min_rom" or "iron_condor.criteria[0]"
    value: Any

    @property
    def file_name(self) -> str:
        """Just the filename without path."""
        return Path(self.file_path).name


@dataclass
class PhaseParameters:
    """Parameters for a single pipeline phase."""
    phase: PipelinePhase
    parameters: Dict[str, ParameterSource] = field(default_factory=dict)

    def add(self, name: str, source: ParameterSource) -> None:
        """Add a parameter."""
        self.parameters[name] = source

    def get(self, name: str) -> Optional[Any]:
        """Get parameter value by name."""
        source = self.parameters.get(name)
        return source.value if source else None

    def items(self) -> List[Tuple[str, ParameterSource]]:
        """Return all parameters as list of tuples."""
        return list(self.parameters.items())


@dataclass
class StrategyConfig:
    """Complete configuration for a single strategy across all phases."""
    strategy_key: str
    strategy_name: str
    greeks_description: str = ""
    phases: Dict[PipelinePhase, PhaseParameters] = field(default_factory=dict)

    def get_phase(self, phase: PipelinePhase) -> PhaseParameters:
        """Get parameters for a specific phase."""
        if phase not in self.phases:
            self.phases[phase] = PhaseParameters(phase=phase)
        return self.phases[phase]

    def all_parameters(self) -> List[Tuple[str, ParameterSource]]:
        """Get all parameters across all phases."""
        result = []
        for phase in PipelinePhase:
            if phase in self.phases:
                result.extend(self.phases[phase].items())
        return result


class ParameterRegistry:
    """Central registry for all pipeline parameters.

    Loads and consolidates parameters from:
    - criteria.yaml (central rules)
    - volatility_rules.yaml (strategy selection)
    - strike_selection_rules.yaml (strike selection)
    - config/strategies.yaml (per-strategy settings)
    - config/backtest.yaml (backtest settings)
    """

    # Known strategies
    STRATEGIES = [
        "iron_condor",
        "atm_iron_butterfly",
        "short_put_spread",
        "short_call_spread",
        "naked_put",
        "calendar",
        "ratio_spread",
        "backspread_put",
    ]

    def __init__(self, base_path: Optional[Path] = None):
        """Initialize the registry.

        Args:
            base_path: Base path for config files. Defaults to project root.
        """
        if base_path is None:
            # Find project root
            base_path = Path(__file__).resolve().parent.parent.parent

        self.base_path = Path(base_path)
        self._configs: Dict[str, StrategyConfig] = {}
        self._raw_data: Dict[str, Any] = {}
        self._file_paths: Dict[str, Path] = {}

        # Define file locations
        self._file_paths = {
            "criteria": self.base_path / "criteria.yaml",
            "volatility_rules": self.base_path / "tomic" / "volatility_rules.yaml",
            "strike_selection": self.base_path / "tomic" / "strike_selection_rules.yaml",
            "strategies": self.base_path / "config" / "strategies.yaml",
            "backtest": self.base_path / "config" / "backtest.yaml",
        }

        self._load_all()

    def _load_yaml(self, key: str) -> Optional[Any]:
        """Load a YAML file by key."""
        path = self._file_paths.get(key)
        if not path or not path.exists():
            logger.warning(f"Config file not found: {path}")
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                self._raw_data[key] = data
                return data
        except Exception as e:
            logger.error(f"Error loading {path}: {e}")
            return None

    def _load_all(self) -> None:
        """Load all configuration files and build strategy configs."""
        # Load all files
        criteria = self._load_yaml("criteria") or {}
        vol_rules = self._load_yaml("volatility_rules") or []
        strike_rules = self._load_yaml("strike_selection") or {}
        strategies = self._load_yaml("strategies") or {}
        backtest = self._load_yaml("backtest") or {}

        # Build config for each strategy
        for strategy_key in self.STRATEGIES:
            config = self._build_strategy_config(
                strategy_key, criteria, vol_rules, strike_rules, strategies, backtest
            )
            self._configs[strategy_key] = config

    def _build_strategy_config(
        self,
        strategy_key: str,
        criteria: Dict,
        vol_rules: List,
        strike_rules: Dict,
        strategies: Dict,
        backtest: Dict,
    ) -> StrategyConfig:
        """Build complete config for a single strategy."""

        # Find volatility rule for this strategy
        vol_rule = next(
            (r for r in vol_rules if r.get("key") == strategy_key),
            {}
        )

        config = StrategyConfig(
            strategy_key=strategy_key,
            strategy_name=vol_rule.get("strategy", strategy_key.replace("_", " ").title()),
            greeks_description=vol_rule.get("greeks", ""),
        )

        # Phase 1: Market Selection (from volatility_rules.yaml)
        market_phase = config.get_phase(PipelinePhase.MARKET_SELECTION)
        if vol_rule.get("criteria"):
            for i, criterion in enumerate(vol_rule["criteria"]):
                market_phase.add(
                    f"criterion_{i+1}",
                    ParameterSource(
                        file_path=str(self._file_paths["volatility_rules"]),
                        yaml_path=f"{strategy_key}.criteria[{i}]",
                        value=criterion,
                    )
                )

        # Phase 2: Strike Selection (from strike_selection_rules.yaml)
        strike_phase = config.get_phase(PipelinePhase.STRIKE_SELECTION)
        strike_config = strike_rules.get(strategy_key, strike_rules.get("default", {}))
        default_config = strike_rules.get("default", {})

        # Merge default with strategy-specific
        merged_strike = {**default_config, **strike_config}

        for key, value in merged_strike.items():
            source_key = strategy_key if key in strike_config else "default"
            strike_phase.add(
                key,
                ParameterSource(
                    file_path=str(self._file_paths["strike_selection"]),
                    yaml_path=f"{source_key}.{key}",
                    value=value,
                )
            )

        # Phase 3: Scoring (from criteria.yaml + strategies.yaml)
        scoring_phase = config.get_phase(PipelinePhase.SCORING)

        # Add generic strike filters from criteria.yaml
        strike_filters = criteria.get("strike", {})
        for key, value in strike_filters.items():
            if value is not None:
                scoring_phase.add(
                    f"strike_{key}",
                    ParameterSource(
                        file_path=str(self._file_paths["criteria"]),
                        yaml_path=f"strike.{key}",
                        value=value,
                    )
                )

        # Add scoring weights from criteria.yaml
        strategy_section = criteria.get("strategy", {})
        scoring_keys = [
            "score_weight_rom", "score_weight_pos", "score_weight_ev", "score_weight_rr",
            "pos_floor_pct", "rom_cap_pct", "ev_cap_pct",
        ]
        for key in scoring_keys:
            if key in strategy_section:
                scoring_phase.add(
                    key,
                    ParameterSource(
                        file_path=str(self._file_paths["criteria"]),
                        yaml_path=f"strategy.{key}",
                        value=strategy_section[key],
                    )
                )

        # Add score labels
        score_labels = strategy_section.get("score_labels", {})
        for key, value in score_labels.items():
            scoring_phase.add(
                f"score_{key}",
                ParameterSource(
                    file_path=str(self._file_paths["criteria"]),
                    yaml_path=f"strategy.score_labels.{key}",
                    value=value,
                )
            )

        # Add per-strategy settings from strategies.yaml
        strat_defaults = strategies.get("default", {})
        strat_specific = strategies.get("strategies", {}).get(strategy_key, {})
        merged_strat = {**strat_defaults, **strat_specific}

        for key, value in merged_strat.items():
            if key == "strike_to_strategy_config":
                # Handle nested config
                for sub_key, sub_value in value.items():
                    source_key = strategy_key if (
                        strategy_key in strategies.get("strategies", {}) and
                        "strike_to_strategy_config" in strategies["strategies"].get(strategy_key, {}) and
                        sub_key in strategies["strategies"][strategy_key]["strike_to_strategy_config"]
                    ) else "default"
                    scoring_phase.add(
                        f"strike_{sub_key}",
                        ParameterSource(
                            file_path=str(self._file_paths["strategies"]),
                            yaml_path=f"{'strategies.' + strategy_key if source_key == strategy_key else 'default'}.strike_to_strategy_config.{sub_key}",
                            value=sub_value,
                        )
                    )
            else:
                source_key = strategy_key if key in strat_specific else "default"
                scoring_phase.add(
                    key,
                    ParameterSource(
                        file_path=str(self._file_paths["strategies"]),
                        yaml_path=f"{'strategies.' + strategy_key if source_key == strategy_key else 'default'}.{key}",
                        value=value,
                    )
                )

        # Phase 4: Exit (from criteria.yaml alerts + backtest.yaml)
        exit_phase = config.get_phase(PipelinePhase.EXIT)

        # Add exit thresholds from criteria.yaml
        risk_thresholds = criteria.get("alerts", {}).get("risk_thresholds", {})
        pnl_theta = risk_thresholds.get("pnl_theta", {})
        for key, value in pnl_theta.items():
            exit_phase.add(
                key,
                ParameterSource(
                    file_path=str(self._file_paths["criteria"]),
                    yaml_path=f"alerts.risk_thresholds.pnl_theta.{key}",
                    value=value,
                )
            )

        # Add DTE threshold
        if "dte_close_threshold" in risk_thresholds:
            exit_phase.add(
                "dte_close_threshold",
                ParameterSource(
                    file_path=str(self._file_paths["criteria"]),
                    yaml_path="alerts.risk_thresholds.dte_close_threshold",
                    value=risk_thresholds["dte_close_threshold"],
                )
            )

        # Add backtest exit rules
        exit_rules = backtest.get("exit_rules", {})
        for key, value in exit_rules.items():
            if value is not None:
                exit_phase.add(
                    f"bt_{key}",
                    ParameterSource(
                        file_path=str(self._file_paths["backtest"]),
                        yaml_path=f"exit_rules.{key}",
                        value=value,
                    )
                )

        # Phase 5: Portfolio Gates (from criteria.yaml)
        portfolio_phase = config.get_phase(PipelinePhase.PORTFOLIO)

        portfolio_section = criteria.get("portfolio", {})
        for key, value in portfolio_section.items():
            if isinstance(value, dict):
                # Handle nested gates like condor_gates
                for sub_key, sub_value in value.items():
                    if sub_value is not None:
                        portfolio_phase.add(
                            f"{key}_{sub_key}",
                            ParameterSource(
                                file_path=str(self._file_paths["criteria"]),
                                yaml_path=f"portfolio.{key}.{sub_key}",
                                value=sub_value,
                            )
                        )
            else:
                if value is not None:
                    portfolio_phase.add(
                        key,
                        ParameterSource(
                            file_path=str(self._file_paths["criteria"]),
                            yaml_path=f"portfolio.{key}",
                            value=value,
                        )
                    )

        return config

    def get_strategy(self, strategy_key: str) -> Optional[StrategyConfig]:
        """Get complete config for a strategy."""
        return self._configs.get(strategy_key)

    def list_strategies(self) -> List[str]:
        """List all available strategies."""
        return list(self._configs.keys())

    def get_all_strategies(self) -> Dict[str, StrategyConfig]:
        """Get all strategy configs."""
        return self._configs.copy()

    def update_parameter(
        self,
        strategy_key: str,
        phase: PipelinePhase,
        param_name: str,
        new_value: Any,
    ) -> bool:
        """Update a parameter and save to the correct file.

        Returns True if successful, False otherwise.
        """
        config = self._configs.get(strategy_key)
        if not config:
            return False

        phase_params = config.phases.get(phase)
        if not phase_params:
            return False

        source = phase_params.parameters.get(param_name)
        if not source:
            return False

        # Update in memory
        old_value = source.value
        source.value = new_value

        # Save to file
        try:
            self._save_parameter(source.file_path, source.yaml_path, new_value)
            logger.info(f"Updated {param_name}: {old_value} -> {new_value} in {source.file_name}")
            return True
        except Exception as e:
            # Rollback
            source.value = old_value
            logger.error(f"Failed to save parameter: {e}")
            return False

    def _save_parameter(self, file_path: str, yaml_path: str, value: Any) -> None:
        """Save a parameter value to its YAML file."""
        path = Path(file_path)

        # Load current file
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        # Navigate and update the value
        # Handle special case for list items (e.g., "iron_condor.criteria[0]")
        if "[" in yaml_path:
            # Parse array index
            base_path, rest = yaml_path.split("[", 1)
            index = int(rest.split("]")[0])

            # Navigate to parent
            parts = base_path.split(".")
            current = data

            # For volatility_rules which is a list at root
            if isinstance(data, list):
                # Find the item with matching key
                for item in data:
                    if item.get("key") == parts[0]:
                        current = item
                        parts = parts[1:]  # Skip the key part
                        break

            for part in parts[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]

            # Get the list and update
            list_key = parts[-1] if parts else None
            if list_key:
                if list_key not in current:
                    current[list_key] = []
                current[list_key][index] = value
        else:
            # Simple path
            parts = yaml_path.split(".")
            current = data

            for part in parts[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]

            current[parts[-1]] = value

        # Write back
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    def reload(self) -> None:
        """Reload all configuration from disk."""
        self._configs.clear()
        self._raw_data.clear()
        self._load_all()

    def get_backtest_config(self) -> Dict[str, Any]:
        """Get the raw backtest configuration."""
        return self._raw_data.get("backtest", {})

    def get_file_path(self, key: str) -> Optional[Path]:
        """Get the file path for a config key."""
        return self._file_paths.get(key)


# Singleton instance
_registry: Optional[ParameterRegistry] = None


def get_registry() -> ParameterRegistry:
    """Get the global parameter registry instance."""
    global _registry
    if _registry is None:
        _registry = ParameterRegistry()
    return _registry


def reload_registry() -> ParameterRegistry:
    """Force reload the registry."""
    global _registry
    _registry = ParameterRegistry()
    return _registry
