"""Asynchronous helpers for market exports."""

from __future__ import annotations

import asyncio

from typing import Iterable

from tomic.logutils import logger, setup_logging
from ._tws_chain_deprecated import removed_tws_chain_entry


async def run_async(
    symbol: str,
    output_dir: str | None = None,
    *,
    fetch_metrics: bool = True,
    fetch_chains: bool = True,
    client_id: int | None = None,
) -> object | None:
    """Run ``tomic.api.getallmarkets.run`` in a background thread."""

    removed_tws_chain_entry()


async def gather_markets(
    symbols: Iterable[str],
    output_dir: str | None = None,
    *,
    fetch_metrics: bool = True,
    fetch_chains: bool = True,
) -> list[object]:
    """Fetch data for multiple markets concurrently."""

    removed_tws_chain_entry()


def main(args: list[str] | None = None) -> None:
    """Entry point for the asynchronous exporter."""

    import argparse

    parser = argparse.ArgumentParser(
        description="Exporteer data voor meerdere markten (async prototype)"
    )
    parser.add_argument("symbols", nargs="*", help="Symbolen om te verwerken")
    parser.add_argument(
        "--output-dir",
        help="Map voor exports (standaard wordt automatisch bepaald)",
    )
    parser.add_argument("--only-metrics", action="store_true", help="Alleen marktdata")
    parser.add_argument(
        "--only-chains", action="store_true", help="Alleen optionchains"
    )
    parsed = parser.parse_args(args)

    setup_logging()
    removed_tws_chain_entry()


if __name__ == "__main__":  # pragma: no cover - manual invocation
    main()
