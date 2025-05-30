import argparse
import logging
import os
import time
from datetime import datetime

from tomic.api.getallmarkets import run, export_combined_csv
from tomic.logging import setup_logging
from tomic.config import get as cfg_get

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Exporteer data voor meerdere markten"
    )
    parser.add_argument("symbols", nargs="*", help="Symbolen om te verwerken")
    parser.add_argument(
        "--output-dir",
        help="Map voor exports (standaard wordt automatisch bepaald)",
    )
    args = parser.parse_args()

    setup_logging()

    default_symbols = [
        "AAPL",
        "ASML",
        "CRM",
        "DIA",
        "EWG",
        "EWJ",
        "EWZ",
        "FEZ",
        "FXI",
        "GLD",
        "INDA",
        "NVDA",
        "QQQ",
        "RUT",
        "SPY",
        "TSLA",
        "VIX",
        "XLE",
        "XLF",
        "XLV",
    ]
    symbols = args.symbols or default_symbols

    if args.output_dir is None:
        today_str = datetime.now().strftime("%Y%m%d")
        export_dir = os.path.join(cfg_get("EXPORT_DIR", "exports"), today_str)
    else:
        export_dir = args.output_dir

    data_frames = []
    for sym in symbols:
        logging.info("🔄 Ophalen voor %s...", sym)
        df = run(sym, export_dir)
        if df is not None:
            data_frames.append(df)
        time.sleep(2)

    unique_markets = {df["Symbol"].iloc[0] for df in data_frames}
    if len(unique_markets) > 1:
        export_combined_csv(data_frames, export_dir)
