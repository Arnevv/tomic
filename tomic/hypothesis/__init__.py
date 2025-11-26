"""Hypothesis testing module for TOMIC.

This module provides tools for creating, testing, and comparing
trading hypotheses to find optimal strategies and parameters.
"""

from tomic.hypothesis.models import (
    Hypothesis,
    HypothesisBatch,
    HypothesisConfig,
    HypothesisScore,
    HypothesisStatus,
)
from tomic.hypothesis.store import (
    HypothesisStore,
    get_store,
)
from tomic.hypothesis.engine import (
    HypothesisEngine,
    run_hypothesis,
)
from tomic.hypothesis.scorecard import (
    SymbolScore,
    SymbolScorecard,
    ScorecardBuilder,
    build_scorecard,
)
from tomic.hypothesis.comparison import (
    HypothesisComparison,
    HypothesisComparator,
    compare_hypotheses,
    compare_last,
)


__all__ = [
    # Models
    "Hypothesis",
    "HypothesisBatch",
    "HypothesisConfig",
    "HypothesisScore",
    "HypothesisStatus",
    # Store
    "HypothesisStore",
    "get_store",
    # Engine
    "HypothesisEngine",
    "run_hypothesis",
    # Scorecard
    "SymbolScore",
    "SymbolScorecard",
    "ScorecardBuilder",
    "build_scorecard",
    # Comparison
    "HypothesisComparison",
    "HypothesisComparator",
    "compare_hypotheses",
    "compare_last",
]
