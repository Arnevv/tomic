"""Store volatility data snapshots via the IB API."""

from typing import List

from tomic.logging import logger

from tomic.logging import setup_logging

from tomic.api.market_utils import fetch_market_metrics
from tomic.analysis.vol_snapshot import (
    store_volatility_snapshot,
    snapshot_symbols as unified_snapshot,
)

def snapshot_symbols(symbols: List[str], output_path: str | None = None) -> None:
    """Fetch metrics via the IB API and store a snapshot for each symbol."""
    unified_snapshot(symbols, fetch_market_metrics, output_path)


def main(argv=None):
    setup_logging()
    logger.info("🚀 Snapshot volatility data")
    if argv is None:
        argv = []
    if not argv:
        syms = (
            input(
                "Symbols kommagescheiden (bv. gld, xlf, xle, crm, aapl, tsla, qqq, dia, spy): "
            )
            .upper()
            .split(",")
        )
        symbols = [s.strip() for s in syms if s.strip()]
    else:
        symbols = [a.upper() for a in argv]
    snapshot_symbols(symbols)
    logger.success("✅ Volatiliteitsdata opgeslagen voor %d symbolen", len(symbols))


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
