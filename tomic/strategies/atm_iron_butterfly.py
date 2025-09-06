from __future__ import annotations

from typing import Any, Dict, List

from . import StrategyName
from .utils import generate_wing_spread
from ..analysis.scoring import calculate_score


def generate(
    symbol: str,
    option_chain: List[Dict[str, Any]],
    config: Dict[str, Any],
    spot: float,
    atr: float,
) -> tuple[List["StrategyProposal"], list[str]]:
    """Generate ATM iron butterfly proposals via :func:`generate_wing_spread`."""

    rules = config.get("strike_to_strategy_config", {})
    return generate_wing_spread(
        symbol,
        option_chain,
        config,
        spot,
        atr,
        strategy_name=StrategyName.ATM_IRON_BUTTERFLY,
        centers=rules.get("center_strike_relative_to_spot", [0]),
        score_func=calculate_score,
    )


__all__ = ["generate"]

