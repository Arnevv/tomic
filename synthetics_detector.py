import json
from typing import Dict, List

from tomic.config import get as cfg_get


def analyze_synthetics_and_edge(strategy: Dict) -> Dict:
    """Detect basic synthetic structures and potential edge."""
    legs = strategy.get("legs", [])
    result = {}
    # check for synthetic long/short stock
    for call in [l for l in legs if (l.get("right") or l.get("type")) == "C"]:
        for put in [p for p in legs if (p.get("right") or p.get("type")) == "P"]:
            if (
                call.get("strike") == put.get("strike")
                and call.get("expiry") == put.get("expiry")
                and call.get("position") == -put.get("position")
            ):
                if call.get("position", 0) > 0:
                    result["synthetic"] = "long_stock"
                else:
                    result["synthetic"] = "short_stock"
    # convexity edge: long gamma while receiving credit
    gamma = strategy.get("gamma")
    cost_basis = strategy.get("cost_basis", 0)
    if gamma and gamma > 0 and cost_basis < 0:
        result["edge"] = "long_gamma_credit"
    return result


def main(argv=None):
    if argv is None:
        argv = []
    positions_file = argv[0] if argv else cfg_get("POSITIONS_FILE", "positions.json")

    from strategy_dashboard import group_strategies

    with open(positions_file, "r", encoding="utf-8") as f:
        positions = json.load(f)
    strategies = group_strategies(positions)
    for strat in strategies:
        res = analyze_synthetics_and_edge(strat)
        if res:
            print(f"{strat['symbol']} {strat['type']} → {res}")


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
