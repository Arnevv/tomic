from __future__ import annotations

"""CLI entrypoint to fetch Polygon intraday prices."""

from typing import List

from tomic.logutils import setup_logging

from .services.intraday_polygon import fetch_polygon_intraday_prices


def main(argv: List[str] | None = None) -> None:
    """Fetch intraday prices for configured or provided symbols."""
    setup_logging()
    symbols = [s.upper() for s in argv] if argv else None
    fetch_polygon_intraday_prices(symbols)


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
