from __future__ import annotations

from typing import Any, Dict, List

from . import StrategyName
from ..strategy_candidates import StrategyProposal
from .utils import RatioStrategySpec, ShortLegSpec, generate_ratio_like



def generate(
    symbol: str,
    option_chain: List[Dict[str, Any]],
    config: Dict[str, Any],
    spot: float,
    atr: float,
) -> tuple[List[StrategyProposal], list[str]]:
    """Generate ratio spread proposals using shared ratio logic."""

    return generate_ratio_like(
        symbol,
        option_chain,
        config,
        spot,
        atr,
        strategy_name=StrategyName.RATIO_SPREAD,
        spec=RatioStrategySpec(
            short_leg=ShortLegSpec(option_type="C", delta_range_key="short_leg_delta_range"),
            use_expiry_pairs=False,
        ),
    )


__all__ = ["generate"]
