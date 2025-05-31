"""CLI helper for exporting data of a single market."""

from tomic.logging import setup_logging
from .market_export import export_market_data


def run(symbol: str, output_dir: str | None = None):
    """Download option chain and market metrics for *symbol*."""

    setup_logging()
    export_market_data(symbol, output_dir)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Exporteer optie- en marktdata")
    parser.add_argument("symbol", help="Ticker symbool")
    parser.add_argument(
        "--output-dir",
        help="Map voor exports (standaard wordt automatisch bepaald)",
    )
    args = parser.parse_args()
    run(args.symbol, args.output_dir)
