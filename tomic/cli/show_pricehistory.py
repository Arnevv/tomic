"""Display price history stored in the volatility database."""
from __future__ import annotations

from typing import List

from tomic.cli._tabulate import tabulate
from tomic.config import get as cfg_get
from tomic.logutils import setup_logging
from tomic.utils import load_price_history


def main(argv: List[str] | None = None) -> None:
    """Print historical prices for one or more symbols."""
    setup_logging()
    if argv is None:
        argv = []
    symbols = [s.upper() for s in argv] if argv else [s.upper() for s in cfg_get("DEFAULT_SYMBOLS", [])]

    for sym in symbols:
        data = load_price_history(sym)
        rows = [
            [rec.get("date"), rec.get("close"), rec.get("volume"), rec.get("atr")]
            for rec in data
        ]
        if rows:
            print(f"\n=== {sym} ===")
            headers = ["date", "close", "volume", "atr"]
            print(tabulate(rows, headers=headers, tablefmt="github"))
        else:
            print(f"\n⚠️ Geen data gevonden voor {sym}")


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
