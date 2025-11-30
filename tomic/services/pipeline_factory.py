"""Factory for creating StrategyPipeline instances."""

from __future__ import annotations

from tomic import config as cfg
from tomic.services.strategy_pipeline import StrategyPipeline


def create_strategy_pipeline() -> StrategyPipeline:
    """Create a StrategyPipeline instance with default configuration.

    Returns a pipeline configured to use the application's global config
    for strike selection and strategy generation.
    """
    return StrategyPipeline(config=cfg.get, market_provider=None)


__all__ = ["create_strategy_pipeline"]
