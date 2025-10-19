from __future__ import annotations

"""CLI entrypoint to fetch Polygon implied volatility data."""

from typing import List

from tomic.logutils import setup_logging

from .services.iv_polygon import fetch_polygon_iv_data


def main(argv: List[str] | None = None) -> None:
    """Fetch implied volatility for configured or provided symbols."""
    setup_logging()
    symbols = [s.upper() for s in argv] if argv else None
    fetch_polygon_iv_data(symbols)


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
