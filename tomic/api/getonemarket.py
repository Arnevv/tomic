"""CLI helper for exporting data of a single market."""

import sys

from tomic.logutils import setup_logging, logger, log_result, trace_calls
from .ib_connection import connect_ib  # backwards compat for tests

def _market_export():
    from . import market_export
    return market_export


@trace_calls
@log_result
def run(
    symbol: str, output_dir: str | None = None, *, simple: bool = False
) -> bool:
    setup_logging()
    export = _market_export()
    if simple:
        res = export.export_option_chain(
            symbol.strip().upper(), output_dir, simple=True, return_status=True
        )
    else:
        res = export.export_market_data(
            symbol.strip().upper(), output_dir, return_status=True
        )
    return not isinstance(res, export.ExportResult) or res.ok


@trace_calls
@log_result
async def run_async(
    symbol: str, output_dir: str | None = None, *, simple: bool = False
) -> bool:
    """Asynchronous entry point for ``getonemarket``."""

    setup_logging()
    export = _market_export()
    if simple:
        res = await export.export_option_chain_async(
            symbol.strip().upper(), output_dir, simple=True, return_status=True
        )
    else:
        res = await export.export_market_data_async(
            symbol.strip().upper(), output_dir, return_status=True
        )
    return not isinstance(res, export.ExportResult) or res.ok


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
