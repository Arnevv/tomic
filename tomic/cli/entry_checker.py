"""Check entry conditions for grouped strategies."""

import json
from typing import List

from tomic.config import get as cfg_get
from tomic.analysis.entry_checks import check_entry_conditions


def main(argv: List[str] | None = None) -> None:
    """Run entry checks on positions JSON."""
    if argv is None:
        argv = []
    positions_file = argv[0] if argv else cfg_get("POSITIONS_FILE", "positions.json")

    from tomic.analysis.strategy import group_strategies

    with open(positions_file, "r", encoding="utf-8") as f:
        positions = json.load(f)
    strategies = group_strategies(positions)
    for strat in strategies:
        warnings = check_entry_conditions(strat)
        if warnings:
            print(f"{strat['symbol']} ({strat['type']}):")
            for w in warnings:
                print(f" - {w}")


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
