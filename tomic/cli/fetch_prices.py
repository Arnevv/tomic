from __future__ import annotations

"""CLI entrypoint to fetch daily price history via Interactive Brokers."""

from typing import List

from tomic.logutils import setup_logging

from .services.price_history_ib import fetch_ib_daily_prices


def main(argv: List[str] | None = None) -> None:
    """Fetch price history for configured or provided symbols."""
    setup_logging()
    symbols = [s.upper() for s in argv] if argv else None
    fetch_ib_daily_prices(symbols)


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
