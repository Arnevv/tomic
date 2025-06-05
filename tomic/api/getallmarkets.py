"""Export market data for multiple symbols."""

from __future__ import annotations

import os
import time
from datetime import datetime

import pandas as pd
from tomic.logging import logger, setup_logging
from tomic.config import get as cfg_get
from .market_export import export_market_data

try:  # pragma: no cover - optional during tests
    from .market_export import export_market_metrics, export_option_chain
except Exception:  # pragma: no cover - when stubs lack these
    export_market_metrics = None  # type: ignore[assignment]
    export_option_chain = None  # type: ignore[assignment]


def run(
    symbol: str,
    output_dir: str | None = None,
    *,
    fetch_metrics: bool = True,
    fetch_chains: bool = True,
) -> pd.DataFrame | None:
    """Download market data and/or option chain for ``symbol``."""

    if fetch_metrics and fetch_chains:
        return export_market_data(symbol, output_dir)
    if fetch_metrics:
        if export_market_metrics is None:
            logger.error("export_market_metrics not available")
            return None
        return export_market_metrics(symbol, output_dir)
    if fetch_chains:
        if export_option_chain is None:
            logger.error("export_option_chain not available")
            return None
        export_option_chain(symbol, output_dir)
    return None


def export_combined_csv(data_per_market: list[pd.DataFrame], output_dir: str) -> None:
    """Combine individual market DataFrames and export to a single CSV."""
    valid_frames = [
        df for df in data_per_market if not df.empty and not df.isna().all().all()
    ]
    if not valid_frames:
        logger.warning("Geen geldige marktdata om te combineren.")
        return
    combined_df = pd.concat(valid_frames, ignore_index=True)
    output_path = os.path.join(output_dir, "Overzicht_Marktkenmerken.csv")
    combined_df.to_csv(output_path, index=False)
    logger.info(f"{len(valid_frames)} markten verwerkt. CSV geëxporteerd.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Exporteer data voor meerdere markten")
    parser.add_argument(
        "symbols",
        nargs="*",
        help="Symbolen om te verwerken",
    )
    parser.add_argument(
        "--output-dir",
        help="Map voor exports (standaard wordt automatisch bepaald)",
    )
    parser.add_argument(
        "--only-metrics",
        action="store_true",
        help="Alleen marktdata ophalen",
    )
    parser.add_argument(
        "--only-chains",
        action="store_true",
        help="Alleen optionchains ophalen",
    )
    args = parser.parse_args()

    setup_logging()
    logger.info("🚀 Start export")

    symbols = args.symbols or cfg_get("DEFAULT_SYMBOLS", [])

    if args.output_dir is None:
        today_str = datetime.now().strftime("%Y%m%d")
        export_dir = os.path.join(cfg_get("EXPORT_DIR", "exports"), today_str)
    else:
        export_dir = args.output_dir

    if args.only_metrics and args.only_chains:
        fetch_metrics = fetch_chains = True
    else:
        fetch_metrics = not args.only_chains
        fetch_chains = not args.only_metrics

    data_frames = []
    for sym in symbols:
        logger.info(f"🔄 Ophalen voor {sym}...")
        df = run(
            sym, export_dir, fetch_metrics=fetch_metrics, fetch_chains=fetch_chains
        )
        if df is not None:
            data_frames.append(df)
        time.sleep(2)

    unique_markets = {df["Symbol"].iloc[0] for df in data_frames}
    if fetch_metrics and len(unique_markets) > 1:
        export_combined_csv(data_frames, export_dir)

    logger.success(f"✅ Export afgerond voor {len(unique_markets)} markten")
