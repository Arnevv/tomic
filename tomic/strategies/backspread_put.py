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
    """Generate backspread put proposals using shared ratio logic."""

    return generate_ratio_like(
        symbol,
        option_chain,
        config,
        spot,
        atr,
        strategy_name=StrategyName.BACKSPREAD_PUT,
        spec=RatioStrategySpec(
            short_leg=ShortLegSpec(option_type="P", delta_range_key="short_put_delta_range"),
            use_expiry_pairs=True,
            max_pairs=3,
        ),
    )


__all__ = ["generate"]
