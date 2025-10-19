from __future__ import annotations

"""CLI entrypoint to compute volatility statistics."""

from typing import List

from tomic.logutils import setup_logging

from .services.volatility import compute_volatility_stats


def main(argv: List[str] | None = None) -> None:
    """Compute volatility statistics for configured or provided symbols."""
    setup_logging()
    symbols = [s.upper() for s in argv] if argv else None
    compute_volatility_stats(symbols)


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
