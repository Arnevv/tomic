from __future__ import annotations

from typing import Any, Dict, List

from . import StrategyName
from ..strategy_candidates import StrategyProposal
from .utils import generate_short_vertical


def generate(
    symbol: str,
    option_chain: List[Dict[str, Any]],
    config: Dict[str, Any],
    spot: float,
    atr: float,
) -> tuple[List[StrategyProposal], list[str]]:
    """Generate short put spread proposals using shared vertical logic."""

    return generate_short_vertical(
        symbol,
        option_chain,
        config,
        spot,
        atr,
        strategy_name=StrategyName.SHORT_PUT_SPREAD,
        option_type="P",
        delta_range_key="short_put_delta_range",
    )


__all__ = ["generate"]

