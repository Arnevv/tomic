"""Export market data for multiple symbols."""

import os
import time
from datetime import datetime

import pandas as pd
from tomic.logging import logger, setup_logging
from tomic.config import get as cfg_get
from .market_export import export_market_data


def run(symbol: str, output_dir: str | None = None):
    """Download option chain and metrics for ``symbol``."""
    return export_market_data(symbol, output_dir)


def export_combined_csv(data_per_market, output_dir):
    """Combine individual market DataFrames and export to a single CSV."""
    combined_df = pd.concat(data_per_market, ignore_index=True)
    output_path = os.path.join(output_dir, "Overzicht_Marktkenmerken.csv")
    combined_df.to_csv(output_path, index=False)
    logger.info("%d markten verwerkt. CSV geëxporteerd.", len(data_per_market))


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
    args = parser.parse_args()

    setup_logging()
    logger.info("🚀 Start export")

    symbols = args.symbols or cfg_get("DEFAULT_SYMBOLS", [])

    if args.output_dir is None:
        today_str = datetime.now().strftime("%Y%m%d")
        export_dir = os.path.join(cfg_get("EXPORT_DIR", "exports"), today_str)
    else:
        export_dir = args.output_dir

    data_frames = []
    for sym in symbols:
        logger.info("🔄 Ophalen voor %s...", sym)
        df = run(sym, export_dir)
        if df is not None:
            data_frames.append(df)
        time.sleep(2)

    unique_markets = {df["Symbol"].iloc[0] for df in data_frames}
    if len(unique_markets) > 1:
        export_combined_csv(data_frames, export_dir)

    logger.success("✅ Export afgerond voor %d markten", len(unique_markets))
