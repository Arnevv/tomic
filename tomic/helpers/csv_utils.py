from __future__ import annotations

"""CSV-related helper utilities."""

import logging
from typing import Iterable, Optional

import pandas as pd

logger = logging.getLogger(__name__)


def normalize_european_number_format(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    """Convert European formatted numbers in ``columns`` to floats.

    Thousands separators using ``.`` are removed and decimal commas are
    replaced with ``.`` before casting to ``float``.
    """
    df = df.copy()
    normed: list[str] = []
    for col in columns:
        if col in df.columns:
            df[col] = df[col].astype(str).apply(
                lambda x: x.replace(".", "").replace(",", ".") if "," in x else x
            )
            df[col] = pd.to_numeric(df[col], errors="coerce")
            normed.append(col)
    if normed:
        logger.info(
            f"\U0001F9EA European number format normalization toegepast op kolommen: {normed}"
        )
    return df


def parse_euro_float(value: Optional[str]) -> Optional[float]:
    """Return ``value`` parsed as float respecting European formatting."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
        try:
            return float(s)
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None
