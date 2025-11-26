"""Hypothesis engine for running and managing hypothesis tests.

Orchestrates the execution of hypotheses using the backtest engine.
"""

from __future__ import annotations

from datetime import datetime, date
from typing import Any, Callable, Dict, List, Optional

from tomic.backtest.engine import run_backtest
from tomic.hypothesis.models import (
    Hypothesis,
    HypothesisBatch,
    HypothesisConfig,
    HypothesisScore,
    HypothesisStatus,
)
from tomic.hypothesis.store import HypothesisStore, get_store
from tomic.logutils import logger


ProgressCallback = Callable[[str, float], None]


class HypothesisEngine:
    """Engine for running hypothesis tests.

    Wraps the backtest engine and adds hypothesis-specific functionality
    like scoring, storage, and batch operations.
    """

    def __init__(self, store: Optional[HypothesisStore] = None):
        """Initialize the hypothesis engine.

        Args:
            store: Hypothesis store to use. Uses default if not provided.
        """
        self.store = store or get_store()

    def create_hypothesis(
        self,
        name: str,
        description: str = "",
        symbols: Optional[List[str]] = None,
        strategy_type: str = "iron_condor",
        iv_percentile_min: float = 60.0,
        profit_target_pct: float = 50.0,
        stop_loss_pct: float = 100.0,
        max_days_in_trade: int = 45,
        start_date: str = "2024-01-01",
        end_date: str = "2025-11-21",
        tags: Optional[List[str]] = None,
        save: bool = True,
    ) -> Hypothesis:
        """Create a new hypothesis.

        Args:
            name: Name for the hypothesis.
            description: Description of what is being tested.
            symbols: List of symbols to test.
            strategy_type: Strategy to use.
            iv_percentile_min: Minimum IV percentile for entry.
            profit_target_pct: Profit target percentage.
            stop_loss_pct: Stop loss percentage.
            max_days_in_trade: Maximum days to hold.
            start_date: Backtest start date.
            end_date: Backtest end date.
            tags: Tags for organization.
            save: Whether to save to store immediately.

        Returns:
            Created Hypothesis instance.
        """
        config = HypothesisConfig(
            name=name,
            description=description,
            symbols=symbols or ["SPY"],
            strategy_type=strategy_type,
            iv_percentile_min=iv_percentile_min,
            profit_target_pct=profit_target_pct,
            stop_loss_pct=stop_loss_pct,
            max_days_in_trade=max_days_in_trade,
            start_date=start_date,
            end_date=end_date,
        )

        hypothesis = Hypothesis(
            config=config,
            tags=tags or [],
        )

        if save:
            self.store.save(hypothesis)

        return hypothesis

    def run(
        self,
        hypothesis: Hypothesis,
        progress_callback: Optional[ProgressCallback] = None,
        save: bool = True,
    ) -> Hypothesis:
        """Run a hypothesis test.

        Args:
            hypothesis: Hypothesis to run.
            progress_callback: Optional callback for progress updates.
            save: Whether to save results to store.

        Returns:
            Updated Hypothesis with results.
        """
        logger.info(f"Running hypothesis: {hypothesis.name}")

        # Update status
        hypothesis.status = HypothesisStatus.RUNNING
        hypothesis.run_at = datetime.now()

        try:
            # Convert to backtest config and run
            backtest_config = hypothesis.config.to_backtest_config()
            result = run_backtest(
                config=backtest_config,
                progress_callback=progress_callback,
            )

            # Store result
            hypothesis.result = result
            hypothesis.status = HypothesisStatus.COMPLETED

            # Calculate score
            if result.combined_metrics:
                start = date.fromisoformat(hypothesis.config.start_date)
                end = date.fromisoformat(hypothesis.config.end_date)
                date_range_days = (end - start).days

                hypothesis.score = HypothesisScore.from_metrics(
                    metrics=result.combined_metrics,
                    degradation_score=result.degradation_score,
                    total_trades=result.combined_metrics.total_trades,
                    date_range_days=date_range_days,
                )

            logger.info(
                f"Hypothesis '{hypothesis.name}' completed: "
                f"{result.combined_metrics.total_trades if result.combined_metrics else 0} trades, "
                f"score: {hypothesis.score.total_score:.1f}" if hypothesis.score else "N/A"
            )

        except Exception as e:
            logger.error(f"Hypothesis '{hypothesis.name}' failed: {e}")
            hypothesis.status = HypothesisStatus.FAILED
            hypothesis.error_message = str(e)

        # Save to store
        if save:
            self.store.save(hypothesis)

        return hypothesis

    def run_by_id(
        self,
        hypothesis_id: str,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> Optional[Hypothesis]:
        """Run a hypothesis by ID.

        Args:
            hypothesis_id: ID of hypothesis to run.
            progress_callback: Optional callback for progress updates.

        Returns:
            Updated Hypothesis, or None if not found.
        """
        hypothesis = self.store.get(hypothesis_id)
        if hypothesis is None:
            logger.warning(f"Hypothesis not found: {hypothesis_id}")
            return None

        return self.run(hypothesis, progress_callback)

    def run_by_name(
        self,
        name: str,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> Optional[Hypothesis]:
        """Run a hypothesis by name.

        Args:
            name: Name of hypothesis to run.
            progress_callback: Optional callback for progress updates.

        Returns:
            Updated Hypothesis, or None if not found.
        """
        hypothesis = self.store.get_by_name(name)
        if hypothesis is None:
            logger.warning(f"Hypothesis not found: {name}")
            return None

        return self.run(hypothesis, progress_callback)

    def create_and_run(
        self,
        name: str,
        progress_callback: Optional[ProgressCallback] = None,
        **kwargs,
    ) -> Hypothesis:
        """Create and immediately run a hypothesis.

        Args:
            name: Name for the hypothesis.
            progress_callback: Optional callback for progress updates.
            **kwargs: Additional arguments passed to create_hypothesis.

        Returns:
            Completed Hypothesis.
        """
        hypothesis = self.create_hypothesis(name, save=False, **kwargs)
        return self.run(hypothesis, progress_callback)

    def clone_hypothesis(
        self,
        hypothesis_id: str,
        new_name: Optional[str] = None,
        save: bool = True,
    ) -> Optional[Hypothesis]:
        """Clone an existing hypothesis with a new ID.

        Creates a copy of the hypothesis configuration ready for modification.

        Args:
            hypothesis_id: ID of hypothesis to clone.
            new_name: Optional new name for the clone.
            save: Whether to save the clone to store immediately.

        Returns:
            Cloned Hypothesis, or None if source not found.
        """
        source = self.store.get(hypothesis_id)
        if source is None:
            logger.warning(f"Hypothesis not found for cloning: {hypothesis_id}")
            return None

        cloned = source.clone(new_name)

        if save:
            self.store.save(cloned)
            logger.info(f"Cloned hypothesis '{source.name}' -> '{cloned.name}' (id: {cloned.id})")

        return cloned

    def update_hypothesis(
        self,
        hypothesis_id: str,
        **updates,
    ) -> Optional[Hypothesis]:
        """Update an existing hypothesis configuration.

        Only allows updating DRAFT hypotheses. For completed hypotheses,
        use clone_hypothesis first.

        Args:
            hypothesis_id: ID of hypothesis to update.
            **updates: Configuration fields to update. Supported fields:
                - name, description, symbols, strategy_type
                - iv_percentile_min, iv_rank_min
                - profit_target_pct, stop_loss_pct, max_days_in_trade
                - start_date, end_date, max_risk_per_trade
                - tags

        Returns:
            Updated Hypothesis, or None if not found or not editable.
        """
        hypothesis = self.store.get(hypothesis_id)
        if hypothesis is None:
            logger.warning(f"Hypothesis not found for update: {hypothesis_id}")
            return None

        # Allow updating DRAFT, FAILED, or even COMPLETED hypotheses
        # But warn for completed ones
        if hypothesis.status == HypothesisStatus.COMPLETED:
            logger.warning(
                f"Updating completed hypothesis '{hypothesis.name}'. "
                "Results will be cleared and hypothesis reset to DRAFT."
            )
            hypothesis.result = None
            hypothesis.score = None
            hypothesis.run_at = None
            hypothesis.error_message = None

        # Reset status to DRAFT for re-running
        hypothesis.status = HypothesisStatus.DRAFT

        # Update config fields
        config_dict = hypothesis.config.to_dict()
        config_fields = {
            "name", "description", "symbols", "strategy_type",
            "iv_percentile_min", "iv_rank_min",
            "profit_target_pct", "stop_loss_pct", "max_days_in_trade",
            "start_date", "end_date", "max_risk_per_trade",
            "expected_win_rate", "expected_sharpe",
        }

        for key, value in updates.items():
            if key in config_fields:
                config_dict[key] = value
            elif key == "tags":
                hypothesis.tags = value

        # Recreate config with updates
        hypothesis.config = HypothesisConfig.from_dict(config_dict)

        # Save
        self.store.save(hypothesis)
        logger.info(f"Updated hypothesis '{hypothesis.name}' (id: {hypothesis.id})")

        return hypothesis

    def run_batch(
        self,
        batch_name: str,
        base_config: Dict[str, Any],
        vary_parameter: str,
        values: List[Any],
        progress_callback: Optional[ProgressCallback] = None,
    ) -> HypothesisBatch:
        """Run a batch of hypotheses varying one parameter.

        Args:
            batch_name: Name for the batch.
            base_config: Base configuration for all hypotheses.
            vary_parameter: Parameter to vary (e.g., "iv_percentile_min").
            values: Values to test for the parameter.
            progress_callback: Optional callback for progress updates.

        Returns:
            HypothesisBatch with all hypothesis IDs.
        """
        batch = HypothesisBatch(
            name=batch_name,
            description=f"Varying {vary_parameter}: {values}",
            varied_parameter=vary_parameter,
            varied_values=values,
        )

        total = len(values)
        for i, value in enumerate(values):
            # Create config with varied parameter
            config = base_config.copy()
            config[vary_parameter] = value

            # Generate name
            hyp_name = f"{batch_name}_{vary_parameter}_{value}"
            config["name"] = hyp_name

            # Progress update
            if progress_callback:
                progress_callback(
                    f"Running {hyp_name} ({i + 1}/{total})",
                    (i / total) * 100,
                )

            # Create and run
            hypothesis = self.create_hypothesis(**config, save=False)
            self.run(hypothesis, save=True)

            batch.hypothesis_ids.append(hypothesis.id)

        # Save batch
        self.store.save_batch(batch)

        if progress_callback:
            progress_callback("Batch complete", 100)

        return batch

    def run_symbol_comparison(
        self,
        symbols: List[str],
        strategy_type: str = "iron_condor",
        iv_percentile_min: float = 60.0,
        batch_name: Optional[str] = None,
        progress_callback: Optional[ProgressCallback] = None,
        **kwargs,
    ) -> HypothesisBatch:
        """Run comparison across multiple symbols.

        Creates one hypothesis per symbol with identical settings.

        Args:
            symbols: Symbols to compare.
            strategy_type: Strategy to use.
            iv_percentile_min: IV percentile threshold.
            batch_name: Optional batch name.
            progress_callback: Optional callback for progress updates.
            **kwargs: Additional config parameters.

        Returns:
            HypothesisBatch with results.
        """
        if batch_name is None:
            batch_name = f"symbol_comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        batch = HypothesisBatch(
            name=batch_name,
            description=f"Symbol comparison: {', '.join(symbols)}",
            varied_parameter="symbols",
            varied_values=symbols,
        )

        total = len(symbols)
        for i, symbol in enumerate(symbols):
            hyp_name = f"{batch_name}_{symbol}"

            if progress_callback:
                progress_callback(
                    f"Running {symbol} ({i + 1}/{total})",
                    (i / total) * 100,
                )

            hypothesis = self.create_hypothesis(
                name=hyp_name,
                symbols=[symbol],
                strategy_type=strategy_type,
                iv_percentile_min=iv_percentile_min,
                save=False,
                **kwargs,
            )
            self.run(hypothesis, save=True)
            batch.hypothesis_ids.append(hypothesis.id)

        self.store.save_batch(batch)

        if progress_callback:
            progress_callback("Comparison complete", 100)

        return batch

    def run_iv_threshold_scan(
        self,
        symbol: str,
        iv_values: Optional[List[float]] = None,
        strategy_type: str = "iron_condor",
        batch_name: Optional[str] = None,
        progress_callback: Optional[ProgressCallback] = None,
        **kwargs,
    ) -> HypothesisBatch:
        """Scan different IV percentile thresholds for a symbol.

        Args:
            symbol: Symbol to test.
            iv_values: IV percentile values to test.
            strategy_type: Strategy to use.
            batch_name: Optional batch name.
            progress_callback: Optional callback for progress updates.
            **kwargs: Additional config parameters.

        Returns:
            HypothesisBatch with results.
        """
        if iv_values is None:
            iv_values = [50.0, 60.0, 70.0, 80.0]

        if batch_name is None:
            batch_name = f"{symbol}_iv_scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        base_config = {
            "symbols": [symbol],
            "strategy_type": strategy_type,
            **kwargs,
        }

        return self.run_batch(
            batch_name=batch_name,
            base_config=base_config,
            vary_parameter="iv_percentile_min",
            values=iv_values,
            progress_callback=progress_callback,
        )

    def run_profit_target_scan(
        self,
        symbol: str,
        profit_values: Optional[List[float]] = None,
        strategy_type: str = "iron_condor",
        batch_name: Optional[str] = None,
        progress_callback: Optional[ProgressCallback] = None,
        **kwargs,
    ) -> HypothesisBatch:
        """Scan different profit target percentages for a symbol.

        Args:
            symbol: Symbol to test.
            profit_values: Profit target values to test.
            strategy_type: Strategy to use.
            batch_name: Optional batch name.
            progress_callback: Optional callback for progress updates.
            **kwargs: Additional config parameters.

        Returns:
            HypothesisBatch with results.
        """
        if profit_values is None:
            profit_values = [30.0, 40.0, 50.0, 60.0, 75.0]

        if batch_name is None:
            batch_name = f"{symbol}_profit_scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        base_config = {
            "symbols": [symbol],
            "strategy_type": strategy_type,
            **kwargs,
        }

        return self.run_batch(
            batch_name=batch_name,
            base_config=base_config,
            vary_parameter="profit_target_pct",
            values=profit_values,
            progress_callback=progress_callback,
        )


# Convenience function
def run_hypothesis(
    name: str,
    progress_callback: Optional[ProgressCallback] = None,
    **kwargs,
) -> Hypothesis:
    """Create and run a hypothesis in one step.

    Args:
        name: Name for the hypothesis.
        progress_callback: Optional callback for progress updates.
        **kwargs: Configuration parameters.

    Returns:
        Completed Hypothesis.
    """
    engine = HypothesisEngine()
    return engine.create_and_run(name, progress_callback, **kwargs)


__all__ = [
    "HypothesisEngine",
    "run_hypothesis",
]
