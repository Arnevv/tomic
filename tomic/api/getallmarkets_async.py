"""Asynchronous helpers for market exports."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
from typing import Iterable, List

from tomic.logging import logger, setup_logging
from tomic.config import get as cfg_get
from .ib_connection import connect_ib

from .getallmarkets import run, export_combined_csv


async def run_async(
    symbol: str,
    output_dir: str | None = None,
    *,
    fetch_metrics: bool = True,
    fetch_chains: bool = True,
) -> object | None:
    """Run ``tomic.api.getallmarkets.run`` in a background thread."""

    return await asyncio.to_thread(
        run,
        symbol,
        output_dir,
        fetch_metrics=fetch_metrics,
        fetch_chains=fetch_chains,
    )


async def gather_markets(
    symbols: Iterable[str],
    output_dir: str | None = None,
    *,
    fetch_metrics: bool = True,
    fetch_chains: bool = True,
) -> list[object]:
    """Fetch data for multiple markets concurrently."""

    tasks = [
        run_async(
            sym,
            output_dir,
            fetch_metrics=fetch_metrics,
            fetch_chains=fetch_chains,
        )
        for sym in symbols
    ]
    results: List = await asyncio.gather(*tasks)

    if output_dir is None:
        today_str = datetime.now().strftime("%Y%m%d")
        output_dir = os.path.join(cfg_get("EXPORT_DIR", "exports"), today_str)

    data_frames = [df for df in results if df is not None]
    if fetch_metrics and len(data_frames) > 1:
        unique_markets = {df["Symbol"].iloc[0] for df in data_frames}
        if len(unique_markets) > 1:
            export_combined_csv(data_frames, output_dir)
    return data_frames


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
    try:
        app = connect_ib()
        app.disconnect()
    except Exception:
        logger.error(
            "❌ IB Gateway/TWS niet bereikbaar. Controleer of de service draait."
        )
        sys.exit(1)

    logger.info("🚀 Start async export")

    symbols = parsed.symbols or cfg_get("DEFAULT_SYMBOLS", [])

    if parsed.only_metrics and parsed.only_chains:
        fetch_metrics = fetch_chains = True
    else:
        fetch_metrics = not parsed.only_chains
        fetch_chains = not parsed.only_metrics

    asyncio.run(
        gather_markets(
            symbols,
            parsed.output_dir,
            fetch_metrics=fetch_metrics,
            fetch_chains=fetch_chains,
        )
    )

    logger.success("✅ Async export afgerond")


if __name__ == "__main__":  # pragma: no cover - manual invocation
    main()
