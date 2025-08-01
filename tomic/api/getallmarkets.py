"""Export market data for multiple symbols."""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime

import pandas as pd
from tomic.logutils import logger, setup_logging
from tomic.config import get as cfg_get
from .ib_connection import connect_ib
from .market_export import export_market_data, ExportResult

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
    client_id: int | None = None,
) -> pd.DataFrame | None:
    """Download market data and/or option chain for ``symbol``."""

    if fetch_metrics and fetch_chains:
        if client_id is None:
            res = export_market_data(symbol, output_dir, return_status=True)
        else:
            res = export_market_data(
                symbol, output_dir, client_id=client_id, return_status=True
            )
        return res.value if isinstance(res, ExportResult) and res.ok else None
    if fetch_metrics:
        if export_market_metrics is None:
            logger.error("export_market_metrics not available")
            return None
        if client_id is None:
            res = export_market_metrics(symbol, output_dir, return_status=True)
        else:
            res = export_market_metrics(
                symbol, output_dir, client_id=client_id, return_status=True
            )
        return res.value if isinstance(res, ExportResult) and res.ok else None
    if fetch_chains:
        if export_option_chain is None:
            logger.error("export_option_chain not available")
            return None
        if client_id is None:
            export_option_chain(symbol, output_dir, return_status=True)
        else:
            export_option_chain(
                symbol, output_dir, client_id=client_id, return_status=True
            )
    return None


def export_combined_csv(data_per_market: list[pd.DataFrame], output_dir: str) -> None:
    """Combine individual market DataFrames and export to a single CSV."""
    valid_frames = [
        df for df in data_per_market if not df.empty and not df.isna().all().all()
    ]
    valid_frames = [df for df in valid_frames if len(getattr(df, "columns", [])) > 0]
    if not valid_frames:
        logger.warning("Geen geldige marktdata om te combineren.")
        return
    combined_df = pd.concat(valid_frames, ignore_index=True)
    output_path = os.path.join(output_dir, "Overzicht_Marktkenmerken.csv")
    combined_df.to_csv(output_path, index=False)
    logger.info(f"{len(valid_frames)} markten verwerkt. CSV geëxporteerd.")


def run_all(
    symbols: list[str] | None = None,
    output_dir: str | None = None,
    *,
    fetch_metrics: bool = True,
    fetch_chains: bool = True,
) -> list[pd.DataFrame]:
    """Download data for ``symbols`` using :func:`run` for each entry."""

    setup_logging()
    try:
        app = connect_ib()
        app.disconnect()
    except Exception:
        logger.error(
            "❌ IB Gateway/TWS niet bereikbaar. Controleer of de service draait."
        )
        raise

    if symbols is None:
        symbols = cfg_get("DEFAULT_SYMBOLS", [])

    if output_dir is None:
        today_str = datetime.now().strftime("%Y%m%d")
        export_dir = os.path.join(cfg_get("EXPORT_DIR", "exports"), today_str)
    else:
        export_dir = output_dir

    data_frames: list[pd.DataFrame] = []
    for sym in symbols:
        logger.info(f"🔄 Ophalen voor {sym}...")
        df = run(sym, export_dir, fetch_metrics=fetch_metrics, fetch_chains=fetch_chains)
        if df is not None:
            data_frames.append(df)
        time.sleep(2)

    unique_markets = {df["Symbol"].iloc[0] for df in data_frames if "Symbol" in getattr(df, "columns", [])}
    if fetch_metrics and len(unique_markets) > 1:
        export_combined_csv(data_frames, export_dir)

    logger.success(f"✅ Export afgerond voor {len(unique_markets)} markten")
    return data_frames


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

    if args.only_metrics and args.only_chains:
        fetch_metrics = fetch_chains = True
    else:
        fetch_metrics = not args.only_chains
        fetch_chains = not args.only_metrics

    try:
        run_all(
            args.symbols or None,
            args.output_dir,
            fetch_metrics=fetch_metrics,
            fetch_chains=fetch_chains,
        )
    except Exception:
        sys.exit(1)
