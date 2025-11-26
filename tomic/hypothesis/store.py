"""Hypothesis store for persistence and retrieval.

Provides JSON-based storage for hypotheses with query capabilities.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from tomic.hypothesis.models import (
    Hypothesis,
    HypothesisBatch,
    HypothesisStatus,
)
from tomic.logutils import logger


class HypothesisStore:
    """Store and retrieve hypotheses.

    Persists hypotheses to JSON files for later analysis and comparison.
    """

    DEFAULT_STORE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "hypotheses.json"

    def __init__(self, store_path: Optional[Path] = None):
        """Initialize store with optional custom path.

        Args:
            store_path: Path to JSON storage file. Uses default if not provided.
        """
        self.store_path = store_path or self.DEFAULT_STORE_PATH
        self._hypotheses: Dict[str, Hypothesis] = {}
        self._batches: Dict[str, HypothesisBatch] = {}
        self._load()

    def _load(self) -> None:
        """Load hypotheses from storage file."""
        if not self.store_path.exists():
            logger.debug(f"Hypothesis store not found at {self.store_path}, starting fresh")
            return

        try:
            with open(self.store_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Load hypotheses
            for hyp_data in data.get("hypotheses", []):
                try:
                    hypothesis = Hypothesis.from_dict(hyp_data)
                    self._hypotheses[hypothesis.id] = hypothesis
                except Exception as e:
                    logger.warning(f"Failed to load hypothesis: {e}")

            # Load batches
            for batch_data in data.get("batches", []):
                try:
                    batch = HypothesisBatch.from_dict(batch_data)
                    self._batches[batch.name] = batch
                except Exception as e:
                    logger.warning(f"Failed to load batch: {e}")

            logger.info(f"Loaded {len(self._hypotheses)} hypotheses from store")

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse hypothesis store: {e}")
        except Exception as e:
            logger.error(f"Failed to load hypothesis store: {e}")

    def _save(self) -> None:
        """Save hypotheses to storage file."""
        # Ensure directory exists
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "version": 1,
            "updated_at": datetime.now().isoformat(),
            "hypotheses": [h.to_dict() for h in self._hypotheses.values()],
            "batches": [b.to_dict() for b in self._batches.values()],
        }

        try:
            with open(self.store_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.debug(f"Saved {len(self._hypotheses)} hypotheses to store")
        except Exception as e:
            logger.error(f"Failed to save hypothesis store: {e}")
            raise

    def save(self, hypothesis: Hypothesis) -> None:
        """Save or update a hypothesis.

        Args:
            hypothesis: Hypothesis to save.
        """
        self._hypotheses[hypothesis.id] = hypothesis
        self._save()
        logger.info(f"Saved hypothesis '{hypothesis.name}' (id: {hypothesis.id})")

    def get(self, hypothesis_id: str) -> Optional[Hypothesis]:
        """Get hypothesis by ID.

        Args:
            hypothesis_id: The hypothesis ID.

        Returns:
            Hypothesis if found, None otherwise.
        """
        return self._hypotheses.get(hypothesis_id)

    def get_by_name(self, name: str) -> Optional[Hypothesis]:
        """Get hypothesis by name.

        Args:
            name: The hypothesis name.

        Returns:
            First hypothesis with matching name, or None.
        """
        for hyp in self._hypotheses.values():
            if hyp.name == name:
                return hyp
        return None

    def delete(self, hypothesis_id: str) -> bool:
        """Delete a hypothesis.

        Args:
            hypothesis_id: The hypothesis ID to delete.

        Returns:
            True if deleted, False if not found.
        """
        if hypothesis_id in self._hypotheses:
            del self._hypotheses[hypothesis_id]
            self._save()
            logger.info(f"Deleted hypothesis {hypothesis_id}")
            return True
        return False

    def list_all(self) -> List[Hypothesis]:
        """Get all hypotheses.

        Returns:
            List of all stored hypotheses, sorted by creation date (newest first).
        """
        return sorted(
            self._hypotheses.values(),
            key=lambda h: h.created_at,
            reverse=True,
        )

    def list_completed(self) -> List[Hypothesis]:
        """Get all completed hypotheses.

        Returns:
            List of completed hypotheses.
        """
        return [h for h in self.list_all() if h.is_completed]

    def get_by_symbol(self, symbol: str) -> List[Hypothesis]:
        """Get hypotheses that include a specific symbol.

        Args:
            symbol: Symbol to filter by (e.g., "SPY").

        Returns:
            List of hypotheses including this symbol.
        """
        return [
            h for h in self.list_completed()
            if symbol.upper() in [s.upper() for s in h.config.symbols]
        ]

    def get_by_strategy(self, strategy: str) -> List[Hypothesis]:
        """Get hypotheses using a specific strategy.

        Args:
            strategy: Strategy type (e.g., "iron_condor").

        Returns:
            List of hypotheses using this strategy.
        """
        return [
            h for h in self.list_completed()
            if h.config.strategy_type.lower() == strategy.lower()
        ]

    def get_by_tag(self, tag: str) -> List[Hypothesis]:
        """Get hypotheses with a specific tag.

        Args:
            tag: Tag to filter by.

        Returns:
            List of hypotheses with this tag.
        """
        return [h for h in self.list_all() if tag in h.tags]

    def get_best_for_symbol(
        self,
        symbol: str,
        limit: int = 5,
        min_trades: int = 10,
    ) -> List[Hypothesis]:
        """Get best performing hypotheses for a symbol.

        Args:
            symbol: Symbol to analyze.
            limit: Maximum number of results.
            min_trades: Minimum trades required.

        Returns:
            List of top hypotheses sorted by score.
        """
        candidates = []
        for hyp in self.get_by_symbol(symbol):
            if (
                hyp.score is not None
                and hyp.result
                and hyp.result.combined_metrics
                and hyp.result.combined_metrics.total_trades >= min_trades
            ):
                candidates.append(hyp)

        # Sort by total score (descending)
        candidates.sort(key=lambda h: h.score.total_score if h.score else 0, reverse=True)
        return candidates[:limit]

    def get_best_overall(
        self,
        limit: int = 10,
        min_trades: int = 10,
    ) -> List[Hypothesis]:
        """Get best performing hypotheses overall.

        Args:
            limit: Maximum number of results.
            min_trades: Minimum trades required.

        Returns:
            List of top hypotheses sorted by score.
        """
        candidates = []
        for hyp in self.list_completed():
            if (
                hyp.score is not None
                and hyp.result
                and hyp.result.combined_metrics
                and hyp.result.combined_metrics.total_trades >= min_trades
            ):
                candidates.append(hyp)

        candidates.sort(key=lambda h: h.score.total_score if h.score else 0, reverse=True)
        return candidates[:limit]

    def get_last_n(self, n: int = 5) -> List[Hypothesis]:
        """Get the last N hypotheses by run date.

        Args:
            n: Number of hypotheses to return.

        Returns:
            List of recently run hypotheses.
        """
        completed = [h for h in self.list_completed() if h.run_at]
        completed.sort(key=lambda h: h.run_at, reverse=True)
        return completed[:n]

    # Batch operations

    def save_batch(self, batch: HypothesisBatch) -> None:
        """Save a hypothesis batch.

        Args:
            batch: Batch to save.
        """
        self._batches[batch.name] = batch
        self._save()

    def get_batch(self, name: str) -> Optional[HypothesisBatch]:
        """Get a batch by name.

        Args:
            name: Batch name.

        Returns:
            Batch if found, None otherwise.
        """
        return self._batches.get(name)

    def list_batches(self) -> List[HypothesisBatch]:
        """Get all batches.

        Returns:
            List of all batches.
        """
        return list(self._batches.values())

    def get_batch_hypotheses(self, batch_name: str) -> List[Hypothesis]:
        """Get all hypotheses in a batch.

        Args:
            batch_name: Name of the batch.

        Returns:
            List of hypotheses in the batch.
        """
        batch = self.get_batch(batch_name)
        if not batch:
            return []

        return [
            self.get(hyp_id)
            for hyp_id in batch.hypothesis_ids
            if self.get(hyp_id) is not None
        ]

    # Statistics

    def get_stats(self) -> Dict[str, Any]:
        """Get summary statistics about stored hypotheses.

        Returns:
            Dictionary with statistics.
        """
        all_hyps = self.list_all()
        completed = self.list_completed()

        # Symbol counts
        symbol_counts: Dict[str, int] = {}
        for hyp in completed:
            for symbol in hyp.config.symbols:
                symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1

        # Strategy counts
        strategy_counts: Dict[str, int] = {}
        for hyp in completed:
            strategy = hyp.config.strategy_type
            strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1

        return {
            "total_hypotheses": len(all_hyps),
            "completed": len(completed),
            "draft": len([h for h in all_hyps if h.status == HypothesisStatus.DRAFT]),
            "failed": len([h for h in all_hyps if h.status == HypothesisStatus.FAILED]),
            "by_symbol": symbol_counts,
            "by_strategy": strategy_counts,
            "total_batches": len(self._batches),
        }

    def clear_all(self) -> None:
        """Clear all hypotheses (use with caution)."""
        self._hypotheses.clear()
        self._batches.clear()
        self._save()
        logger.warning("Cleared all hypotheses from store")


# Singleton instance for convenience
_default_store: Optional[HypothesisStore] = None


def get_store() -> HypothesisStore:
    """Get the default hypothesis store instance.

    Returns:
        The default HypothesisStore.
    """
    global _default_store
    if _default_store is None:
        _default_store = HypothesisStore()
    return _default_store


__all__ = [
    "HypothesisStore",
    "get_store",
]
