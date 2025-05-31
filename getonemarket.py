import argparse

from tomic.api.getonemarket import run
from tomic.logging import setup_logging

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Optieketen en marktdata export")
    parser.add_argument("symbol", nargs="?", help="Ticker symbool")
    parser.add_argument(
        "--output-dir",
        help="Map voor exports (standaard wordt automatisch bepaald)",
    )
    args = parser.parse_args()

    if args.symbol is None:
        args.symbol = input(
            "\U0001f4c8 Voer het symbool in waarvoor je data wilt ophalen (bijv. SPY): "
        ).strip()

    setup_logging()
    run(args.symbol, args.output_dir)
