"""CLI helper for exporting data of a single market."""

import sys

from tomic.logutils import setup_logging, logger, log_result, trace_calls
from .market_export import export_market_data
from .ib_connection import connect_ib

@trace_calls
@log_result
def run(symbol: str, output_dir: str | None = None) -> bool:
    setup_logging()
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
