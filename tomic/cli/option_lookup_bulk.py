"""Interactively fetch option chain data using BulkQualifyFlow."""

from __future__ import annotations

from tomic.logutils import setup_logging
from tomic.api.market_export import export_option_chain_bulk, ExportResult
from .common import prompt


def run() -> None:
    """Prompt user for a symbol and export its option chain."""
    setup_logging()
    symbol = prompt("Ticker symbool: ").upper()
    if not symbol:
        print("Geen symbool opgegeven")
        return

    res = export_option_chain_bulk(symbol, return_status=True)
    if isinstance(res, ExportResult) and not res.ok:
        print(f"❌ Export mislukt: {res.error}")
    else:
        print(f"✅ Optieketen geëxporteerd voor {symbol}")


def main(argv: list[str] | None = None) -> None:
    """CLI entry point for exporting an option chain with bulk validation."""
    if argv:
        if len(argv) not in (1, 2):
            print("Usage: option_lookup_bulk SYMBOL [OUTPUT_DIR]")
            return
        symbol = argv[0]
        output_dir = argv[1] if len(argv) == 2 else None
        setup_logging()
        res = export_option_chain_bulk(symbol.upper(), output_dir, return_status=True)
        if isinstance(res, ExportResult) and not res.ok:
            print(f"❌ Export mislukt: {res.error}")
        else:
            print(f"✅ Optieketen geëxporteerd voor {symbol.upper()}")
    else:
        run()


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
