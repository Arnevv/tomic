from __future__ import annotations

"""CSV-related helper utilities."""

import logging
from typing import Iterable, Optional

import pandas as pd

logger = logging.getLogger(__name__)


def normalize_european_number_format(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    """Convert European formatted numbers in ``columns`` to floats."""

    df = df.copy()
    normalized: list[str] = []

    for col in columns:
        if col not in df.columns:
            continue

        original = df[col].copy()
        series = original.astype(str)

        needs_conversion = series.str.contains(",", na=False)
        if needs_conversion.any():
            formatted = series.where(
                ~needs_conversion,
                series.str.replace(".", "", regex=False).str.replace(",", ".", regex=False),
            )
        else:
            formatted = series

        converted = pd.to_numeric(formatted, errors="coerce")
        df[col] = converted

        if not converted.equals(original):
            normalized.append(col)

    if normalized:
        logger.info(
            "\U0001F9EA European number format normalization toegepast op kolommen: %s",
            normalized,
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
