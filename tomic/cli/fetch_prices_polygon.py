from __future__ import annotations

"""CLI entrypoint to fetch daily price history via Polygon."""

print("🚀 Script bootstrap start")  # stdout fallback

from typing import List

from tomic.logutils import setup_logging

from .services.price_history_polygon import fetch_polygon_price_history


def main(argv: List[str] | None = None) -> None:
    """Fetch Polygon price history for configured or provided symbols."""
    setup_logging()
    symbols = [s.upper() for s in argv] if argv else None
    fetch_polygon_price_history(symbols)


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
