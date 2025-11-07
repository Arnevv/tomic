"""CLI helper for exporting data of a single market."""

import sys

from tomic.logutils import log_result, setup_logging, trace_calls

from ._tws_chain_deprecated import removed_tws_chain_entry


@trace_calls
@log_result
def run(
    symbol: str, output_dir: str | None = None, *, simple: bool = False
) -> bool:
    setup_logging()
    removed_tws_chain_entry()


@trace_calls
@log_result
async def run_async(
    symbol: str, output_dir: str | None = None, *, simple: bool = False
) -> bool:
    """Asynchronous entry point for ``getonemarket``."""

    setup_logging()
    removed_tws_chain_entry()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Exporteer optie- en marktdata")
    parser.add_argument("symbol", help="Ticker symbool")
    parser.add_argument(
        "--output-dir",
        help="Map voor exports (standaard wordt automatisch bepaald)",
    )
    parser.add_argument(
        "--simple",
        action="store_true",
        help="Gebruik eenvoudige writer voor optieketen",
    )
    args = parser.parse_args()
    if not run(args.symbol, args.output_dir, simple=args.simple):
        sys.exit(1)
