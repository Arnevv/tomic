"""Data models for hypothesis testing system.

This module provides the core data structures for creating, storing,
and analyzing trading hypotheses.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import Any, Dict, List, Optional

from tomic.backtest.config import (
    BacktestConfig,
    EntryRulesConfig,
    ExitRulesConfig,
)
from tomic.backtest.results import BacktestResult, PerformanceMetrics


class HypothesisStatus(Enum):
    """Status of a hypothesis."""

    DRAFT = "draft"           # Created but not yet run
    RUNNING = "running"       # Currently being executed
    COMPLETED = "completed"   # Successfully completed
    FAILED = "failed"         # Execution failed


@dataclass
class HypothesisConfig:
    """Configuration for a hypothesis test.

    Extends BacktestConfig with hypothesis-specific metadata.
    """

    # Hypothesis metadata
    name: str
    description: str = ""

    # Core backtest parameters
    symbols: List[str] = field(default_factory=lambda: ["SPY"])
    strategy_type: str = "iron_condor"

    # Date range
    start_date: str = "2024-01-01"
    end_date: str = "2025-11-21"

    # Entry rules
    iv_percentile_min: float = 60.0
    iv_rank_min: Optional[float] = None

    # Exit rules
    profit_target_pct: float = 50.0
    stop_loss_pct: float = 100.0
    max_days_in_trade: int = 45

    # Position sizing
    max_risk_per_trade: float = 200.0

    # Optional: expected outcomes for validation
    expected_win_rate: Optional[str] = None  # e.g., ">65%"
    expected_sharpe: Optional[str] = None    # e.g., ">1.2"

    def to_backtest_config(self) -> BacktestConfig:
        """Convert hypothesis config to BacktestConfig for running."""
        entry_rules = EntryRulesConfig(
            iv_percentile_min=self.iv_percentile_min,
            iv_rank_min=self.iv_rank_min,
        )

        exit_rules = ExitRulesConfig(
            profit_target_pct=self.profit_target_pct,
            stop_loss_pct=self.stop_loss_pct,
            max_days_in_trade=self.max_days_in_trade,
        )

        return BacktestConfig(
            strategy_type=self.strategy_type,
            symbols=self.symbols,
            start_date=self.start_date,
            end_date=self.end_date,
            entry_rules=entry_rules,
            exit_rules=exit_rules,
        )

    @classmethod
    def from_backtest_config(
        cls,
        config: BacktestConfig,
        name: str,
        description: str = "",
    ) -> "HypothesisConfig":
        """Create HypothesisConfig from existing BacktestConfig."""
        return cls(
            name=name,
            description=description,
            symbols=config.symbols,
            strategy_type=config.strategy_type,
            start_date=config.start_date,
            end_date=config.end_date,
            iv_percentile_min=config.entry_rules.iv_percentile_min,
            iv_rank_min=config.entry_rules.iv_rank_min,
            profit_target_pct=config.exit_rules.profit_target_pct,
            stop_loss_pct=config.exit_rules.stop_loss_pct,
            max_days_in_trade=config.exit_rules.max_days_in_trade,
            max_risk_per_trade=config.position_sizing.max_risk_per_trade,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "description": self.description,
            "symbols": self.symbols,
            "strategy_type": self.strategy_type,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "iv_percentile_min": self.iv_percentile_min,
            "iv_rank_min": self.iv_rank_min,
            "profit_target_pct": self.profit_target_pct,
            "stop_loss_pct": self.stop_loss_pct,
            "max_days_in_trade": self.max_days_in_trade,
            "max_risk_per_trade": self.max_risk_per_trade,
            "expected_win_rate": self.expected_win_rate,
            "expected_sharpe": self.expected_sharpe,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HypothesisConfig":
        """Create from dictionary."""
        return cls(**data)


@dataclass
class HypothesisScore:
    """Composite score for ranking hypotheses.

    Combines multiple metrics into a single quality score.
    """

    # Individual components (0-100 scale)
    win_rate_score: float = 0.0
    sharpe_score: float = 0.0
    stability_score: float = 0.0  # Based on degradation
    trade_frequency_score: float = 0.0

    # Weights
    WIN_RATE_WEIGHT: float = 0.30
    SHARPE_WEIGHT: float = 0.35
    STABILITY_WEIGHT: float = 0.20
    FREQUENCY_WEIGHT: float = 0.15

    @property
    def total_score(self) -> float:
        """Calculate weighted total score (0-100)."""
        return (
            self.win_rate_score * self.WIN_RATE_WEIGHT +
            self.sharpe_score * self.SHARPE_WEIGHT +
            self.stability_score * self.STABILITY_WEIGHT +
            self.trade_frequency_score * self.FREQUENCY_WEIGHT
        )

    @classmethod
    def from_metrics(
        cls,
        metrics: PerformanceMetrics,
        degradation_score: float,
        total_trades: int,
        date_range_days: int,
    ) -> "HypothesisScore":
        """Calculate score from performance metrics."""
        # Win rate score: 50% = 0, 80% = 100
        win_rate_score = max(0, min(100, (metrics.win_rate - 50) * (100 / 30)))

        # Sharpe score: 0 = 0, 2.0 = 100
        sharpe_score = max(0, min(100, metrics.sharpe_ratio * 50))

        # Stability score: 0% degradation = 100, 50% = 0
        stability_score = max(0, 100 - (degradation_score * 2))

        # Trade frequency score: trades per 30 days
        # 0.5 trades/month = 0, 4+ trades/month = 100
        trades_per_month = (total_trades / date_range_days) * 30 if date_range_days > 0 else 0
        trade_frequency_score = max(0, min(100, (trades_per_month - 0.5) * (100 / 3.5)))

        return cls(
            win_rate_score=win_rate_score,
            sharpe_score=sharpe_score,
            stability_score=stability_score,
            trade_frequency_score=trade_frequency_score,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "win_rate_score": self.win_rate_score,
            "sharpe_score": self.sharpe_score,
            "stability_score": self.stability_score,
            "trade_frequency_score": self.trade_frequency_score,
            "total_score": self.total_score,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HypothesisScore":
        """Create from dictionary."""
        return cls(
            win_rate_score=data.get("win_rate_score", 0),
            sharpe_score=data.get("sharpe_score", 0),
            stability_score=data.get("stability_score", 0),
            trade_frequency_score=data.get("trade_frequency_score", 0),
        )


@dataclass
class Hypothesis:
    """A complete hypothesis with configuration and results.

    Represents a named, testable trading hypothesis that can be
    stored, compared, and analyzed.
    """

    # Identity
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    # Configuration
    config: HypothesisConfig = field(default_factory=lambda: HypothesisConfig(name="unnamed"))

    # Metadata
    created_at: datetime = field(default_factory=datetime.now)
    run_at: Optional[datetime] = None
    status: HypothesisStatus = HypothesisStatus.DRAFT

    # Results (populated after run)
    result: Optional[BacktestResult] = None
    score: Optional[HypothesisScore] = None
    error_message: Optional[str] = None

    # Tags for organizing
    tags: List[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        """Get hypothesis name."""
        return self.config.name

    @property
    def is_completed(self) -> bool:
        """Check if hypothesis has been run successfully."""
        return self.status == HypothesisStatus.COMPLETED and self.result is not None

    def get_summary_metrics(self) -> Dict[str, Any]:
        """Get key metrics for quick display."""
        if not self.is_completed or not self.result or not self.result.combined_metrics:
            return {}

        metrics = self.result.combined_metrics
        return {
            "trades": metrics.total_trades,
            "win_rate": f"{metrics.win_rate:.1f}%",
            "sharpe": f"{metrics.sharpe_ratio:.2f}",
            "total_pnl": f"${metrics.total_pnl:.0f}",
            "profit_factor": f"{metrics.profit_factor:.2f}",
            "max_drawdown": f"{metrics.max_drawdown_pct:.1f}%",
            "degradation": f"{self.result.degradation_score:.1f}%",
            "score": f"{self.score.total_score:.0f}" if self.score else "N/A",
        }

    def clone(self, new_name: Optional[str] = None) -> "Hypothesis":
        """Create a clone of this hypothesis with a new ID.

        Creates a fresh copy with DRAFT status, ready for modification and running.
        The original hypothesis is not modified.

        Args:
            new_name: Optional new name for the clone. If not provided,
                     the original name with " (kopie)" suffix is used.

        Returns:
            New Hypothesis instance with cloned configuration.
        """
        # Clone the config
        config_dict = self.config.to_dict()
        if new_name:
            config_dict["name"] = new_name
        else:
            config_dict["name"] = f"{self.config.name} (kopie)"

        cloned_config = HypothesisConfig.from_dict(config_dict)

        # Create new hypothesis with fresh ID and DRAFT status
        return Hypothesis(
            config=cloned_config,
            tags=self.tags.copy(),
            # Reset status to DRAFT - this is a fresh copy
            status=HypothesisStatus.DRAFT,
            # Do not copy result, score, run_at, or error_message
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        data = {
            "id": self.id,
            "config": self.config.to_dict(),
            "created_at": self.created_at.isoformat(),
            "run_at": self.run_at.isoformat() if self.run_at else None,
            "status": self.status.value,
            "tags": self.tags,
            "error_message": self.error_message,
        }

        # Add score if available
        if self.score:
            data["score"] = self.score.to_dict()

        # Add result summary (not full result to keep file size manageable)
        if self.result:
            data["result_summary"] = {
                "total_trades": len(self.result.trades),
                "start_date": self.result.start_date.isoformat() if self.result.start_date else None,
                "end_date": self.result.end_date.isoformat() if self.result.end_date else None,
                "degradation_score": self.result.degradation_score,
                "is_valid": self.result.is_valid,
            }
            if self.result.combined_metrics:
                metrics = self.result.combined_metrics
                data["result_summary"]["metrics"] = {
                    "total_trades": metrics.total_trades,
                    "win_rate": metrics.win_rate,
                    "total_pnl": metrics.total_pnl,
                    "sharpe_ratio": metrics.sharpe_ratio,
                    "profit_factor": metrics.profit_factor,
                    "max_drawdown_pct": metrics.max_drawdown_pct,
                    "avg_days_in_trade": metrics.avg_days_in_trade,
                    "exits_by_reason": metrics.exits_by_reason,
                    "metrics_by_symbol": metrics.metrics_by_symbol,
                }

        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Hypothesis":
        """Create from dictionary (partial restoration without full result)."""
        config = HypothesisConfig.from_dict(data["config"])

        hypothesis = cls(
            id=data["id"],
            config=config,
            created_at=datetime.fromisoformat(data["created_at"]),
            run_at=datetime.fromisoformat(data["run_at"]) if data.get("run_at") else None,
            status=HypothesisStatus(data["status"]),
            tags=data.get("tags", []),
            error_message=data.get("error_message"),
        )

        # Restore score if available
        if "score" in data:
            hypothesis.score = HypothesisScore.from_dict(data["score"])

        # Note: Full BacktestResult is not restored from dict
        # Only summary is available after loading from store

        return hypothesis


@dataclass
class HypothesisBatch:
    """A batch of related hypotheses for comparison.

    Used when running multiple variations (e.g., different IV thresholds).
    """

    name: str
    description: str = ""
    created_at: datetime = field(default_factory=datetime.now)

    # Hypothesis IDs in this batch
    hypothesis_ids: List[str] = field(default_factory=list)

    # What parameter was varied
    varied_parameter: Optional[str] = None  # e.g., "iv_percentile_min"
    varied_values: List[Any] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at.isoformat(),
            "hypothesis_ids": self.hypothesis_ids,
            "varied_parameter": self.varied_parameter,
            "varied_values": self.varied_values,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HypothesisBatch":
        """Create from dictionary."""
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            created_at=datetime.fromisoformat(data["created_at"]),
            hypothesis_ids=data.get("hypothesis_ids", []),
            varied_parameter=data.get("varied_parameter"),
            varied_values=data.get("varied_values", []),
        )


__all__ = [
    "HypothesisStatus",
    "HypothesisConfig",
    "HypothesisScore",
    "Hypothesis",
    "HypothesisBatch",
]
