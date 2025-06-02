"""Check entry conditions for grouped strategies."""

from typing import List

from tomic.config import get as cfg_get
from tomic.analysis.alerts import check_entry_conditions
from tomic.journal.utils import load_json


def main(argv: List[str] | None = None) -> None:
    """Run entry checks on positions JSON."""
    if argv is None:
        argv = []
    positions_file = argv[0] if argv else cfg_get("POSITIONS_FILE", "positions.json")

    from tomic.analysis.strategy import group_strategies

    positions = load_json(positions_file)
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
