"""Store volatility data snapshots via the IB API."""

from typing import List

from tomic.logging import logger

from tomic.logging import setup_logging

from tomic.api.market_utils import fetch_market_metrics
from tomic.analysis.vol_snapshot import snapshot_symbols


def main(argv: List[str] | None = None) -> None:
    """Prompt for symbols and store a volatility snapshot."""
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
    snapshot_symbols(symbols, fetch_market_metrics)
    logger.success("✅ Volatiliteitsdata opgeslagen voor %d symbolen", len(symbols))


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
