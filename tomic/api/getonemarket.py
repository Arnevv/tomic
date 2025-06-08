"""CLI helper for exporting data of a single market."""

import sys

from tomic.logutils import setup_logging, logger
from .market_export import export_market_data
from .ib_connection import connect_ib

def run(symbol: str, output_dir: str | None = None, *, queue_job: bool = False) -> bool:
    """Download option chain and market metrics for *symbol*.

    Returns ``True`` on success, ``False`` when no TWS connection is available.
    """

    setup_logging()
    if queue_job:
        submit_task(
            {
                "type": "get_market_data",
                "symbol": symbol.strip().upper(),
                "output_dir": output_dir,
            }
        )
        logger.success("Job toegevoegd aan queue")
        return True
    try:
        app = connect_ib()
        app.disconnect()
    except Exception as exc:
        logger.error(f"❌ Geen verbinding met TWS: {exc}")
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
    parser.add_argument(
        "--queue",
        action="store_true",
        help="Alleen een job aanmaken voor de TwsSessionDaemon",
    )
    args = parser.parse_args()
    if not run(args.symbol, args.output_dir, queue_job=args.queue):
        sys.exit(1)
