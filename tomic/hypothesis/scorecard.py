"""Symbol scorecard for predictability analysis.

Analyzes symbols based on historical performance and IV characteristics
to determine their suitability for premium selling strategies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from tomic.hypothesis.models import Hypothesis
from tomic.hypothesis.store import HypothesisStore, get_store
from tomic.logutils import logger


@dataclass
class SymbolScore:
    """Predictability score for a single symbol.

    Combines multiple factors into a single score (0-100) indicating
    how suitable a symbol is for systematic premium selling.
    """

    symbol: str

    # Performance metrics from hypotheses
    best_win_rate: float = 0.0
    best_sharpe: float = 0.0
    avg_win_rate: float = 0.0
    avg_sharpe: float = 0.0

    # Stability metrics
    avg_degradation: float = 0.0  # Lower is better

    # Trade frequency
    avg_trades_per_hypothesis: float = 0.0
    iv_opportunity_days: int = 0  # Days with IV >= 60%

    # Best configuration found
    best_iv_threshold: Optional[float] = None
    best_profit_target: Optional[float] = None
    best_strategy: Optional[str] = None

    # Hypothesis count
    hypothesis_count: int = 0

    @property
    def win_rate_score(self) -> float:
        """Score based on win rate (0-100)."""
        # 50% = 0, 80% = 100
        return max(0, min(100, (self.best_win_rate - 50) * (100 / 30)))

    @property
    def sharpe_score(self) -> float:
        """Score based on Sharpe ratio (0-100)."""
        # 0 = 0, 2.0 = 100
        return max(0, min(100, self.best_sharpe * 50))

    @property
    def stability_score(self) -> float:
        """Score based on degradation (0-100)."""
        # 0% degradation = 100, 50% = 0
        return max(0, 100 - (self.avg_degradation * 2))

    @property
    def frequency_score(self) -> float:
        """Score based on trade frequency (0-100)."""
        # Scale based on average trades per hypothesis
        # 5 = 0, 50+ = 100
        return max(0, min(100, (self.avg_trades_per_hypothesis - 5) * (100 / 45)))

    @property
    def predictability_score(self) -> float:
        """Overall predictability score (0-100).

        Weighted combination of all factors.
        """
        if self.hypothesis_count == 0:
            return 0.0

        return (
            self.win_rate_score * 0.30 +
            self.sharpe_score * 0.35 +
            self.stability_score * 0.20 +
            self.frequency_score * 0.15
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "symbol": self.symbol,
            "predictability_score": self.predictability_score,
            "win_rate_score": self.win_rate_score,
            "sharpe_score": self.sharpe_score,
            "stability_score": self.stability_score,
            "frequency_score": self.frequency_score,
            "best_win_rate": self.best_win_rate,
            "best_sharpe": self.best_sharpe,
            "avg_degradation": self.avg_degradation,
            "avg_trades": self.avg_trades_per_hypothesis,
            "best_iv_threshold": self.best_iv_threshold,
            "best_profit_target": self.best_profit_target,
            "best_strategy": self.best_strategy,
            "hypothesis_count": self.hypothesis_count,
        }


@dataclass
class SymbolScorecard:
    """Complete scorecard with all analyzed symbols.

    Provides rankings and comparisons across symbols.
    """

    scores: Dict[str, SymbolScore] = field(default_factory=dict)
    generated_at: Optional[date] = None

    def add_score(self, score: SymbolScore) -> None:
        """Add a symbol score."""
        self.scores[score.symbol] = score

    def get_score(self, symbol: str) -> Optional[SymbolScore]:
        """Get score for a symbol."""
        return self.scores.get(symbol.upper())

    def get_ranked_symbols(self) -> List[SymbolScore]:
        """Get symbols ranked by predictability score.

        Returns:
            List of SymbolScore sorted by score (descending).
        """
        return sorted(
            self.scores.values(),
            key=lambda s: s.predictability_score,
            reverse=True,
        )

    def get_top_symbols(self, n: int = 5) -> List[SymbolScore]:
        """Get top N symbols by predictability.

        Args:
            n: Number of symbols to return.

        Returns:
            Top N SymbolScore instances.
        """
        return self.get_ranked_symbols()[:n]

    def get_recommendations(self) -> Dict[str, Any]:
        """Generate recommendations based on scores.

        Returns:
            Dictionary with recommendations.
        """
        ranked = self.get_ranked_symbols()

        if not ranked:
            return {"message": "No hypothesis data available for recommendations"}

        recommendations = {
            "top_symbols": [],
            "avoid_symbols": [],
            "best_configurations": [],
        }

        for score in ranked[:3]:
            rec = {
                "symbol": score.symbol,
                "score": score.predictability_score,
                "best_strategy": score.best_strategy,
                "best_iv_threshold": score.best_iv_threshold,
            }
            recommendations["top_symbols"].append(rec)

        # Symbols to potentially avoid (low scores)
        for score in ranked[-3:]:
            if score.predictability_score < 50:
                recommendations["avoid_symbols"].append({
                    "symbol": score.symbol,
                    "score": score.predictability_score,
                    "reason": "Low predictability score",
                })

        # Best configurations per symbol
        for score in ranked:
            if score.best_win_rate > 60:
                recommendations["best_configurations"].append({
                    "symbol": score.symbol,
                    "strategy": score.best_strategy or "iron_condor",
                    "iv_threshold": score.best_iv_threshold or 60.0,
                    "profit_target": score.best_profit_target or 50.0,
                    "expected_win_rate": f"{score.best_win_rate:.1f}%",
                })

        return recommendations

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
            "scores": {s: score.to_dict() for s, score in self.scores.items()},
            "rankings": [
                {"rank": i + 1, "symbol": s.symbol, "score": s.predictability_score}
                for i, s in enumerate(self.get_ranked_symbols())
            ],
        }


class ScorecardBuilder:
    """Build symbol scorecards from hypothesis data."""

    def __init__(self, store: Optional[HypothesisStore] = None):
        """Initialize builder.

        Args:
            store: Hypothesis store to use.
        """
        self.store = store or get_store()

    def build(self, symbols: Optional[List[str]] = None) -> SymbolScorecard:
        """Build scorecard from stored hypotheses.

        Args:
            symbols: Symbols to include. If None, includes all.

        Returns:
            Generated SymbolScorecard.
        """
        scorecard = SymbolScorecard(generated_at=date.today())

        # Get all completed hypotheses
        hypotheses = self.store.list_completed()

        if not hypotheses:
            logger.warning("No completed hypotheses found for scorecard")
            return scorecard

        # Group by symbol
        symbol_hypotheses: Dict[str, List[Hypothesis]] = {}
        for hyp in hypotheses:
            for symbol in hyp.config.symbols:
                symbol = symbol.upper()
                if symbols and symbol not in [s.upper() for s in symbols]:
                    continue
                if symbol not in symbol_hypotheses:
                    symbol_hypotheses[symbol] = []
                symbol_hypotheses[symbol].append(hyp)

        # Calculate scores for each symbol
        for symbol, hyps in symbol_hypotheses.items():
            score = self._calculate_symbol_score(symbol, hyps)
            scorecard.add_score(score)

        logger.info(f"Built scorecard for {len(scorecard.scores)} symbols")
        return scorecard

    def _calculate_symbol_score(
        self,
        symbol: str,
        hypotheses: List[Hypothesis],
    ) -> SymbolScore:
        """Calculate score for a single symbol.

        Args:
            symbol: Symbol being scored.
            hypotheses: Hypotheses involving this symbol.

        Returns:
            Calculated SymbolScore.
        """
        score = SymbolScore(symbol=symbol)
        score.hypothesis_count = len(hypotheses)

        if not hypotheses:
            return score

        # Collect metrics from all hypotheses
        win_rates = []
        sharpes = []
        degradations = []
        trade_counts = []

        best_hypothesis: Optional[Hypothesis] = None
        best_total_score = 0.0

        for hyp in hypotheses:
            if not hyp.result or not hyp.result.combined_metrics:
                continue

            metrics = hyp.result.combined_metrics

            win_rates.append(metrics.win_rate)
            sharpes.append(metrics.sharpe_ratio)
            degradations.append(hyp.result.degradation_score)
            trade_counts.append(metrics.total_trades)

            # Track best hypothesis
            if hyp.score and hyp.score.total_score > best_total_score:
                best_total_score = hyp.score.total_score
                best_hypothesis = hyp

        # Calculate aggregates
        if win_rates:
            score.best_win_rate = max(win_rates)
            score.avg_win_rate = sum(win_rates) / len(win_rates)

        if sharpes:
            score.best_sharpe = max(sharpes)
            score.avg_sharpe = sum(sharpes) / len(sharpes)

        if degradations:
            score.avg_degradation = sum(degradations) / len(degradations)

        if trade_counts:
            score.avg_trades_per_hypothesis = sum(trade_counts) / len(trade_counts)

        # Best configuration
        if best_hypothesis:
            score.best_iv_threshold = best_hypothesis.config.iv_percentile_min
            score.best_profit_target = best_hypothesis.config.profit_target_pct
            score.best_strategy = best_hypothesis.config.strategy_type

        return score

    def build_comparison_report(
        self,
        symbols: List[str],
    ) -> Dict[str, Any]:
        """Build a comparison report for specific symbols.

        Args:
            symbols: Symbols to compare.

        Returns:
            Comparison report dictionary.
        """
        scorecard = self.build(symbols)

        report = {
            "symbols_compared": symbols,
            "rankings": [],
            "detailed_scores": {},
            "recommendations": scorecard.get_recommendations(),
        }

        for rank, score in enumerate(scorecard.get_ranked_symbols(), 1):
            report["rankings"].append({
                "rank": rank,
                "symbol": score.symbol,
                "predictability_score": f"{score.predictability_score:.0f}",
                "best_win_rate": f"{score.best_win_rate:.1f}%",
                "best_sharpe": f"{score.best_sharpe:.2f}",
                "avg_degradation": f"{score.avg_degradation:.1f}%",
            })
            report["detailed_scores"][score.symbol] = score.to_dict()

        return report


def build_scorecard(symbols: Optional[List[str]] = None) -> SymbolScorecard:
    """Convenience function to build a scorecard.

    Args:
        symbols: Optional list of symbols to include.

    Returns:
        Generated SymbolScorecard.
    """
    builder = ScorecardBuilder()
    return builder.build(symbols)


__all__ = [
    "SymbolScore",
    "SymbolScorecard",
    "ScorecardBuilder",
    "build_scorecard",
]
