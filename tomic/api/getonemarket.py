"""CLI helper for exporting data of a single market."""

import sys

from tomic.logging import setup_logging, logger
from .market_export import export_market_data
from .market_utils import ib_connection_available


def run(symbol: str, output_dir: str | None = None) -> bool:
    """Download option chain and market metrics for *symbol*.

    Returns ``True`` on success, ``False`` when no TWS connection is available.
    """

    setup_logging()
    if not ib_connection_available():
        logger.error(
            "❌ IB Gateway/TWS niet bereikbaar. Controleer of de service draait."
        )
        return False
    export_market_data(symbol.strip().upper(), output_dir)
    return True


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Exporteer optie- en marktdata")
    parser.add_argument("symbol", help="Ticker symbool")
    parser.add_argument(
        "--output-dir",
        help="Map voor exports (standaard wordt automatisch bepaald)",
    )
    args = parser.parse_args()
    if not run(args.symbol, args.output_dir):
        sys.exit(1)
