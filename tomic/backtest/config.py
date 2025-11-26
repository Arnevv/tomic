"""Backtest configuration models and loading utilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict


class EntryRulesConfig(BaseModel):
    """Entry rules configuration for backtest signals."""

    iv_percentile_min: float = 60.0
    iv_rank_min: Optional[float] = None
    skew_min: Optional[float] = None
    skew_max: Optional[float] = None
    term_structure_min: Optional[float] = None
    term_structure_max: Optional[float] = None
    iv_hv_spread_min: Optional[float] = None

    model_config = ConfigDict(extra="forbid")


class ExitRulesConfig(BaseModel):
    """Exit rules configuration based on Dennis Chen / TOMIC principles."""

    profit_target_pct: float = 50.0  # 50% of credit received
    stop_loss_pct: float = 100.0  # 100% of credit (can be 100-150%)
    min_dte: int = 5  # Exit at 5 DTE to avoid gamma risk
    max_days_in_trade: int = 45  # Dennis Chen max holding period
    iv_collapse_threshold: float = 10.0  # Exit if IV drops 10 vol points
    delta_breach_threshold: float = 20.0  # Exit if position delta > 20

    model_config = ConfigDict(extra="forbid")


class PositionSizingConfig(BaseModel):
    """Position sizing configuration."""

    type: str = "fixed_risk"  # fixed_risk | percent_equity
    max_risk_per_trade: float = 200.0  # $200 fixed risk per trade
    max_positions_per_symbol: int = 1  # Only 1 position per symbol at a time
    max_total_positions: int = 10  # Max concurrent positions across all symbols

    model_config = ConfigDict(extra="forbid")


class SampleSplitConfig(BaseModel):
    """Configuration for in-sample / out-of-sample splitting."""

    in_sample_ratio: float = 0.30  # 30% in-sample
    method: str = "chronological"  # chronological | random (only chronological for trading)

    model_config = ConfigDict(extra="forbid")


class CostConfig(BaseModel):
    """Transaction cost assumptions."""

    commission_per_contract: float = 1.0  # $1 per contract
    slippage_pct: float = 5.0  # 5% of credit as slippage

    model_config = ConfigDict(extra="forbid")


class BacktestConfig(BaseModel):
    """Main backtest configuration model.

    This configuration controls all aspects of the backtesting process:
    - Strategy type and symbols
    - Entry and exit rules
    - Position sizing
    - Sample splitting for validation
    - Date range for historical data
    """

    version: int = 1
    strategy_type: str = "iron_condor"
    symbols: List[str] = field(
        default_factory=lambda: ["SPY", "QQQ", "IWM", "AAPL", "MSFT"]
    )

    # Date range for backtest
    #start_date: str = "2007-01-01" #dit was oude data, later te herstellen als ik meer data heb
    #end_date: str = "2024-12-31" #dit was oude data, later te herstellen als ik meer data heb

    start_date: str = "2025-05-01"
    end_date: str = "2025-11-21"

    # Target DTE for new positions
    target_dte: int = 45

    # Nested configuration sections
    entry_rules: EntryRulesConfig = field(default_factory=EntryRulesConfig)
    exit_rules: ExitRulesConfig = field(default_factory=ExitRulesConfig)
    position_sizing: PositionSizingConfig = field(default_factory=PositionSizingConfig)
    sample_split: SampleSplitConfig = field(default_factory=SampleSplitConfig)
    costs: CostConfig = field(default_factory=CostConfig)

    # Iron Condor specific parameters
    iron_condor_wing_width: int = 5  # Strike width between short and long legs
    iron_condor_short_delta: float = 0.16  # Target delta for short strikes (~1 SD)

    # P&L Model selection
    use_greeks_model: bool = False  # Use Greeks-based model instead of IV-based model

    model_config = ConfigDict(extra="forbid")

    def get_in_sample_end_date(self) -> date:
        """Calculate the end date for in-sample period based on split ratio."""
        start = date.fromisoformat(self.start_date)
        end = date.fromisoformat(self.end_date)
        total_days = (end - start).days
        in_sample_days = int(total_days * self.sample_split.in_sample_ratio)
        from datetime import timedelta

        return start + timedelta(days=in_sample_days)

    def get_out_sample_start_date(self) -> date:
        """Calculate the start date for out-of-sample period."""
        from datetime import timedelta

        return self.get_in_sample_end_date() + timedelta(days=1)


# Use field with default_factory for mutable defaults
def _make_default_symbols() -> List[str]:
    return ["SPY", "QQQ", "IWM", "AAPL", "MSFT"]


# Re-define BacktestConfig properly for Pydantic v2
class BacktestConfig(BaseModel):
    """Main backtest configuration model."""

    version: int = 1
    strategy_type: str = "iron_condor"
    symbols: List[str] = ["SPY", "QQQ", "IWM", "AAPL", "MSFT"]

    start_date: str = "2007-01-01"
    end_date: str = "2024-12-31"
    target_dte: int = 45

    entry_rules: EntryRulesConfig = EntryRulesConfig()
    exit_rules: ExitRulesConfig = ExitRulesConfig()
    position_sizing: PositionSizingConfig = PositionSizingConfig()
    sample_split: SampleSplitConfig = SampleSplitConfig()
    costs: CostConfig = CostConfig()

    iron_condor_wing_width: int = 5
    iron_condor_short_delta: float = 0.16

    model_config = ConfigDict(extra="forbid")

    def get_in_sample_end_date(self) -> date:
        """Calculate the end date for in-sample period based on split ratio."""
        start = date.fromisoformat(self.start_date)
        end = date.fromisoformat(self.end_date)
        total_days = (end - start).days
        in_sample_days = int(total_days * self.sample_split.in_sample_ratio)
        from datetime import timedelta

        return start + timedelta(days=in_sample_days)

    def get_out_sample_start_date(self) -> date:
        """Calculate the start date for out-of-sample period."""
        from datetime import timedelta

        return self.get_in_sample_end_date() + timedelta(days=1)


def _load_yaml(path: Path) -> Dict[str, Any]:
    """Load YAML configuration file."""
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML required for YAML config") from exc

    with open(path, "r", encoding="utf-8") as f:
        content = yaml.safe_load(f)
    return content or {}


def load_backtest_config(path: Optional[Path] = None) -> BacktestConfig:
    """Load backtest configuration from YAML file.

    Args:
        path: Path to the backtest.yaml file. If None, uses default location.

    Returns:
        BacktestConfig instance with loaded or default values.
    """
    if path is None:
        # Default location: config/backtest.yaml
        base_dir = Path(__file__).resolve().parent.parent.parent
        path = base_dir / "config" / "backtest.yaml"

    if not path.exists():
        # Return default config if file doesn't exist
        return BacktestConfig()

    data = _load_yaml(path)

    # Handle nested configs
    if "entry_rules" in data and isinstance(data["entry_rules"], dict):
        data["entry_rules"] = EntryRulesConfig(**data["entry_rules"])
    if "exit_rules" in data and isinstance(data["exit_rules"], dict):
        data["exit_rules"] = ExitRulesConfig(**data["exit_rules"])
    if "position_sizing" in data and isinstance(data["position_sizing"], dict):
        data["position_sizing"] = PositionSizingConfig(**data["position_sizing"])
    if "sample_split" in data and isinstance(data["sample_split"], dict):
        data["sample_split"] = SampleSplitConfig(**data["sample_split"])
    if "costs" in data and isinstance(data["costs"], dict):
        data["costs"] = CostConfig(**data["costs"])

    return BacktestConfig(**data)


def save_backtest_config(config: BacktestConfig, path: Optional[Path] = None) -> None:
    """Save backtest configuration to YAML file.

    Args:
        config: BacktestConfig instance to save.
        path: Path to save the file. If None, uses default location.
    """
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML required for YAML config") from exc

    if path is None:
        base_dir = Path(__file__).resolve().parent.parent.parent
        path = base_dir / "config" / "backtest.yaml"

    # Ensure directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    # Convert to dict for YAML serialization
    if hasattr(config, "model_dump"):
        data = config.model_dump()
    else:
        data = config.dict()

    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)


__all__ = [
    "BacktestConfig",
    "EntryRulesConfig",
    "ExitRulesConfig",
    "PositionSizingConfig",
    "SampleSplitConfig",
    "CostConfig",
    "load_backtest_config",
    "save_backtest_config",
]
