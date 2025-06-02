"""Detect synthetic positions in strategies."""

from typing import Any, Dict, List

from tomic.config import get as cfg_get
from tomic.journal.utils import load_json


def analyze_synthetics_and_edge(strategy: Dict[str, Any]) -> Dict[str, Any]:
    """Detect basic synthetic structures and potential edge."""
    legs = strategy.get("legs", [])
    result = {}
    # check for synthetic long/short stock
    for call_leg in [
        leg for leg in legs if (leg.get("right") or leg.get("type")) == "C"
    ]:
        for put_leg in [
            leg for leg in legs if (leg.get("right") or leg.get("type")) == "P"
        ]:
            if (
                call_leg.get("strike") == put_leg.get("strike")
                and call_leg.get("expiry") == put_leg.get("expiry")
                and call_leg.get("position") == -put_leg.get("position")
            ):
                if call_leg.get("position", 0) > 0:
                    result["synthetic"] = "long_stock"
                else:
                    result["synthetic"] = "short_stock"
    # convexity edge: long gamma while receiving credit
    gamma = strategy.get("gamma")
    cost_basis = strategy.get("cost_basis", 0)
    if gamma and gamma > 0 and cost_basis < 0:
        result["edge"] = "long_gamma_credit"
    return result


def main(argv: List[str] | None = None) -> None:
    """Analyse open positions for synthetic structures."""
    if argv is None:
        argv = []
    positions_file = argv[0] if argv else cfg_get("POSITIONS_FILE", "positions.json")

    from tomic.analysis.strategy import group_strategies

    positions = load_json(positions_file)
    strategies = group_strategies(positions)
    for strat in strategies:
        res = analyze_synthetics_and_edge(strat)
        if res:
            print(f"{strat['symbol']} {strat['type']} → {res}")


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
