"""Interactively fetch option chain data for a symbol."""

from __future__ import annotations

from tomic.logutils import setup_logging
from tomic.api.market_export import export_option_chain
from .common import prompt


def run() -> None:
    """Prompt user for a symbol and export its option chain."""
    setup_logging()
    symbol = prompt("Ticker symbool: ").upper()
    if not symbol:
        print("Geen symbool opgegeven")
        return

    export_option_chain(symbol)
    print(f"✅ Optieketen geëxporteerd voor {symbol}")


def main(argv: list[str] | None = None) -> None:
    """CLI entry point for exporting an option chain."""
    if argv:
        if len(argv) not in (1, 2):
            print("Usage: option_lookup SYMBOL [OUTPUT_DIR]")
            return
        symbol = argv[0]
        output_dir = argv[1] if len(argv) == 2 else None
        setup_logging()
        export_option_chain(symbol.upper(), output_dir)
        print(f"✅ Optieketen geëxporteerd voor {symbol.upper()}")
    else:
        run()


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
