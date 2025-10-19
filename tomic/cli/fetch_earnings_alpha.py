from __future__ import annotations

"""CLI entrypoint to fetch upcoming earnings via Alpha Vantage."""

from typing import List

from tomic.logutils import setup_logging

from .services.earnings_alpha import update_alpha_earnings


def main(argv: List[str] | None = None) -> None:
    """Fetch earnings dates for configured or provided symbols."""
    setup_logging()
    symbols = [s.upper() for s in argv] if argv else None
    update_alpha_earnings(symbols)


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
