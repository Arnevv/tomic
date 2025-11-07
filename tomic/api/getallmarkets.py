"""Deprecated TWS market export entrypoints."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Iterable

import pandas as pd

from tomic.config import get as cfg_get
from tomic.logutils import logger

from ._tws_chain_deprecated import removed_tws_chain_entry


def _ensure_enabled() -> None:
    removed_tws_chain_entry()


def run(*_: object, **__: object) -> None:
    """Legacy entry point that now fails fast with a clear error."""

    _ensure_enabled()


def run_all(*_: object, **__: object) -> None:
    """Legacy bulk entry point that now fails fast with a clear error."""

    _ensure_enabled()


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


def export_combined_csv_for_iterable(frames: Iterable[pd.DataFrame], output_dir: str) -> None:
    """Helper retained for backwards compatibility with async exporters."""

    export_combined_csv(list(frames), output_dir)


def default_export_dir() -> str:
    """Return the directory where legacy exports would be stored."""

    today_str = datetime.now().strftime("%Y%m%d")
    return os.path.join(cfg_get("EXPORT_DIR", "exports"), today_str)


__all__ = [
    "run",
    "run_all",
    "export_combined_csv",
    "export_combined_csv_for_iterable",
    "default_export_dir",
]
