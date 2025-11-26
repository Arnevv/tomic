"""Hypothesis comparison and reporting.

Compare multiple hypotheses and generate reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from tomic.hypothesis.models import Hypothesis
from tomic.hypothesis.store import HypothesisStore, get_store


@dataclass
class ComparisonMetric:
    """A single metric being compared across hypotheses."""

    name: str
    values: Dict[str, Any] = field(default_factory=dict)  # hypothesis_id -> value
    best_id: Optional[str] = None
    best_value: Optional[Any] = None


@dataclass
class HypothesisComparison:
    """Comparison results for multiple hypotheses."""

    hypotheses: List[Hypothesis] = field(default_factory=list)
    metrics: Dict[str, ComparisonMetric] = field(default_factory=dict)
    generated_at: datetime = field(default_factory=datetime.now)

    # Rankings (hypothesis_id -> rank)
    rankings: Dict[str, int] = field(default_factory=dict)

    def get_winner(self) -> Optional[Hypothesis]:
        """Get the best performing hypothesis.

        Returns:
            Best hypothesis based on overall score.
        """
        if not self.rankings:
            return None

        best_id = min(self.rankings, key=self.rankings.get)
        for hyp in self.hypotheses:
            if hyp.id == best_id:
                return hyp
        return None

    def get_metric(self, metric_name: str) -> Optional[ComparisonMetric]:
        """Get a specific metric comparison.

        Args:
            metric_name: Name of the metric.

        Returns:
            ComparisonMetric if found.
        """
        return self.metrics.get(metric_name)

    def to_table_data(self) -> List[Dict[str, Any]]:
        """Convert to table format for display.

        Returns:
            List of rows for table display.
        """
        rows = []
        for hyp in sorted(self.hypotheses, key=lambda h: self.rankings.get(h.id, 999)):
            if not hyp.result or not hyp.result.combined_metrics:
                continue

            metrics = hyp.result.combined_metrics
            row = {
                "rank": self.rankings.get(hyp.id, "-"),
                "name": hyp.name,
                "symbol": ", ".join(hyp.config.symbols),
                "trades": metrics.total_trades,
                "win_rate": f"{metrics.win_rate:.1f}%",
                "sharpe": f"{metrics.sharpe_ratio:.2f}",
                "total_pnl": f"${metrics.total_pnl:.0f}",
                "profit_factor": f"{metrics.profit_factor:.2f}",
                "max_dd": f"{metrics.max_drawdown_pct:.1f}%",
                "degradation": f"{hyp.result.degradation_score:.1f}%",
                "score": f"{hyp.score.total_score:.0f}" if hyp.score else "N/A",
            }
            rows.append(row)
        return rows

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "generated_at": self.generated_at.isoformat(),
            "hypothesis_count": len(self.hypotheses),
            "rankings": [
                {"rank": rank, "hypothesis_id": hid, "name": self._get_name(hid)}
                for hid, rank in sorted(self.rankings.items(), key=lambda x: x[1])
            ],
            "metrics": {
                name: {
                    "values": metric.values,
                    "best_id": metric.best_id,
                    "best_value": metric.best_value,
                }
                for name, metric in self.metrics.items()
            },
            "table_data": self.to_table_data(),
        }

    def _get_name(self, hypothesis_id: str) -> str:
        """Get hypothesis name by ID."""
        for hyp in self.hypotheses:
            if hyp.id == hypothesis_id:
                return hyp.name
        return "Unknown"


class HypothesisComparator:
    """Compare multiple hypotheses."""

    def __init__(self, store: Optional[HypothesisStore] = None):
        """Initialize comparator.

        Args:
            store: Hypothesis store to use.
        """
        self.store = store or get_store()

    def compare(
        self,
        hypotheses: List[Hypothesis],
        rank_by: str = "score",
    ) -> HypothesisComparison:
        """Compare a list of hypotheses.

        Args:
            hypotheses: Hypotheses to compare.
            rank_by: Metric to rank by (score, win_rate, sharpe, profit_factor).

        Returns:
            HypothesisComparison with results.
        """
        comparison = HypothesisComparison(hypotheses=hypotheses)

        # Skip hypotheses without results
        valid_hypotheses = [
            h for h in hypotheses
            if h.result and h.result.combined_metrics
        ]

        if not valid_hypotheses:
            return comparison

        # Extract metrics
        metrics_to_compare = [
            ("win_rate", lambda h: h.result.combined_metrics.win_rate, True),
            ("sharpe", lambda h: h.result.combined_metrics.sharpe_ratio, True),
            ("total_pnl", lambda h: h.result.combined_metrics.total_pnl, True),
            ("profit_factor", lambda h: h.result.combined_metrics.profit_factor, True),
            ("max_drawdown", lambda h: h.result.combined_metrics.max_drawdown_pct, False),
            ("degradation", lambda h: h.result.degradation_score, False),
            ("total_trades", lambda h: h.result.combined_metrics.total_trades, True),
            ("score", lambda h: h.score.total_score if h.score else 0, True),
        ]

        for metric_name, extractor, higher_is_better in metrics_to_compare:
            metric = ComparisonMetric(name=metric_name)

            for hyp in valid_hypotheses:
                try:
                    value = extractor(hyp)
                    metric.values[hyp.id] = value
                except (AttributeError, TypeError):
                    metric.values[hyp.id] = None

            # Find best
            valid_values = {k: v for k, v in metric.values.items() if v is not None}
            if valid_values:
                if higher_is_better:
                    metric.best_id = max(valid_values, key=valid_values.get)
                else:
                    metric.best_id = min(valid_values, key=valid_values.get)
                metric.best_value = valid_values[metric.best_id]

            comparison.metrics[metric_name] = metric

        # Calculate rankings
        comparison.rankings = self._calculate_rankings(valid_hypotheses, rank_by)

        return comparison

    def compare_by_ids(
        self,
        hypothesis_ids: List[str],
        rank_by: str = "score",
    ) -> HypothesisComparison:
        """Compare hypotheses by their IDs.

        Args:
            hypothesis_ids: IDs of hypotheses to compare.
            rank_by: Metric to rank by.

        Returns:
            HypothesisComparison with results.
        """
        hypotheses = []
        for hid in hypothesis_ids:
            hyp = self.store.get(hid)
            if hyp:
                hypotheses.append(hyp)

        return self.compare(hypotheses, rank_by)

    def compare_last_n(
        self,
        n: int = 5,
        rank_by: str = "score",
    ) -> HypothesisComparison:
        """Compare the last N hypotheses.

        Args:
            n: Number of recent hypotheses to compare.
            rank_by: Metric to rank by.

        Returns:
            HypothesisComparison with results.
        """
        hypotheses = self.store.get_last_n(n)
        return self.compare(hypotheses, rank_by)

    def compare_batch(
        self,
        batch_name: str,
        rank_by: str = "score",
    ) -> HypothesisComparison:
        """Compare all hypotheses in a batch.

        Args:
            batch_name: Name of the batch.
            rank_by: Metric to rank by.

        Returns:
            HypothesisComparison with results.
        """
        hypotheses = self.store.get_batch_hypotheses(batch_name)
        return self.compare(hypotheses, rank_by)

    def _calculate_rankings(
        self,
        hypotheses: List[Hypothesis],
        rank_by: str,
    ) -> Dict[str, int]:
        """Calculate rankings based on specified metric.

        Args:
            hypotheses: Hypotheses to rank.
            rank_by: Metric to rank by.

        Returns:
            Dictionary mapping hypothesis ID to rank (1 = best).
        """
        if not hypotheses:
            return {}

        # Define how to extract the ranking value
        extractors = {
            "score": lambda h: h.score.total_score if h.score else 0,
            "win_rate": lambda h: h.result.combined_metrics.win_rate,
            "sharpe": lambda h: h.result.combined_metrics.sharpe_ratio,
            "profit_factor": lambda h: h.result.combined_metrics.profit_factor,
            "total_pnl": lambda h: h.result.combined_metrics.total_pnl,
        }

        extractor = extractors.get(rank_by, extractors["score"])

        # Sort hypotheses (higher is better)
        sorted_hypotheses = sorted(
            hypotheses,
            key=lambda h: extractor(h) if h.result and h.result.combined_metrics else 0,
            reverse=True,
        )

        # Assign ranks
        rankings = {}
        for rank, hyp in enumerate(sorted_hypotheses, 1):
            rankings[hyp.id] = rank

        return rankings


def compare_hypotheses(
    hypothesis_ids: List[str],
    rank_by: str = "score",
) -> HypothesisComparison:
    """Convenience function to compare hypotheses by ID.

    Args:
        hypothesis_ids: IDs of hypotheses to compare.
        rank_by: Metric to rank by.

    Returns:
        HypothesisComparison with results.
    """
    comparator = HypothesisComparator()
    return comparator.compare_by_ids(hypothesis_ids, rank_by)


def compare_last(n: int = 5, rank_by: str = "score") -> HypothesisComparison:
    """Compare the last N hypotheses.

    Args:
        n: Number of recent hypotheses.
        rank_by: Metric to rank by.

    Returns:
        HypothesisComparison with results.
    """
    comparator = HypothesisComparator()
    return comparator.compare_last_n(n, rank_by)


__all__ = [
    "ComparisonMetric",
    "HypothesisComparison",
    "HypothesisComparator",
    "compare_hypotheses",
    "compare_last",
]
