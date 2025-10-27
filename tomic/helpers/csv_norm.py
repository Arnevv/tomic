from __future__ import annotations

"""DataFrame helpers for normalising option chain CSV exports."""

from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd

from .csv_utils import normalize_european_number_format


_DEFAULT_COLUMN_ALIASES: dict[str, str] = {"expiration": "expiry"}


def _lowercase_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Return ``df`` with lowercase column names."""

    df = df.copy()
    df.columns = [str(col).strip().lower() for col in df.columns]
    return df


def _apply_column_aliases(
    df: pd.DataFrame, aliases: Mapping[str, str] | None
) -> pd.DataFrame:
    """Rename aliased columns and drop duplicates when canonical already exists."""

    if not aliases:
        return df

    df = df.copy()
    normalized_aliases = {
        str(source).lower(): str(target).lower() for source, target in aliases.items()
    }
    rename_map: dict[str, str] = {}
    drop_columns: list[str] = []
    # Track canonical targets that already have a column assigned so that we keep the
    # first occurrence and drop subsequent alias matches.
    assigned_targets: set[str] = set(df.columns)

    for column in list(df.columns):
        target = normalized_aliases.get(column)
        if not target:
            continue
        if target in assigned_targets and target != column:
            drop_columns.append(column)
        else:
            rename_map[column] = target
            assigned_targets.add(target)

    if drop_columns:
        df = df.drop(columns=drop_columns)
    if rename_map:
        df = df.rename(columns=rename_map)
    return df


def _format_date_columns(
    df: pd.DataFrame, columns: Iterable[str], date_format: str
) -> pd.DataFrame:
    """Format ``columns`` as dates using ``date_format`` when present."""

    if not columns:
        return df

    df = df.copy()
    for column in columns:
        if column in df.columns:
            df[column] = (
                pd.to_datetime(df[column], errors="coerce")
                .dt.strftime(date_format)
                .where(lambda series: series.notna(), None)
            )
    return df


def normalize_chain_dataframe(
    df: pd.DataFrame,
    *,
    decimal_columns: Iterable[str] = (),
    column_aliases: Mapping[str, str] | None = None,
    date_columns: Iterable[str] = ("expiry",),
    date_format: str = "%Y-%m-%d",
) -> pd.DataFrame:
    """Normalise ``df`` for downstream option chain processing."""

    if column_aliases:
        aliases = {**_DEFAULT_COLUMN_ALIASES, **column_aliases}
    else:
        aliases = dict(_DEFAULT_COLUMN_ALIASES)

    df = _lowercase_columns(df)
    df = _apply_column_aliases(df, aliases)
    df = normalize_european_number_format(df, decimal_columns)
    df = _format_date_columns(df, date_columns, date_format)
    return df


def dataframe_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert ``df`` to plain records while sanitising NaN values."""

    records: list[dict[str, Any]] = []
    for row in df.to_dict(orient="records"):
        sanitized: dict[str, Any] = {}
        for key, value in row.items():
            if value is None:
                sanitized[key] = None
                continue
            if isinstance(value, float) and pd.isna(value):
                sanitized[key] = None
                continue
            if pd.isna(value):
                sanitized[key] = None
                continue
            if hasattr(value, "item"):
                try:
                    sanitized[key] = value.item()
                    continue
                except Exception:  # pragma: no cover - defensive
                    pass
            sanitized[key] = value
        records.append(sanitized)
    return records
