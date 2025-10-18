from __future__ import annotations

"""CLI entrypoint for historical volatility backfills."""

import argparse
from typing import Sequence

from tomic.logutils import setup_logging
from tomic.services.marketdata import HistoricalVolatilityBackfillService


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill historical volatility files using Polygon prices.",
    )
    parser.add_argument(
        "symbols",
        nargs="*",
        help="Specifieke tickers om te backfillen. Laat leeg voor default-config.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def run_backfill_hv(symbols: Sequence[str] | None = None) -> None:
    service = HistoricalVolatilityBackfillService()
    service.run(symbols)


def main(argv: Sequence[str] | None = None) -> None:
    setup_logging()
    args = parse_args(argv)
    run_backfill_hv(args.symbols or None)


if __name__ == "__main__":  # pragma: no cover - script entrypoint
    main()
