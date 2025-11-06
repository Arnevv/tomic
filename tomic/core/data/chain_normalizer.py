"""Normalization helpers for option chain records.

This module centralises the logic that prepares option chain data for
downstream processing.  Both CSV based loaders and runtime feeds can use the
helpers to ensure consistent formatting and parity reconstruction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import math
from typing import Any, Callable, Iterable, Mapping, Sequence

try:  # pragma: no cover - optional dependency for type checking
    import pandas as pd  # type: ignore
except Exception:  # pragma: no cover - pandas optional at runtime
    pd = None  # type: ignore

from ...helpers.csv_norm import dataframe_to_records, normalize_chain_dataframe
from ...helpers.dateutils import dte_between_dates
from ...helpers.numeric import safe_float
from ...utils import get_leg_right, normalize_leg, today

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class ChainNormalizerConfig:
    """Configuration for normalising option chain tabular data."""

    decimal_columns: Sequence[str] = (
        "bid",
        "ask",
        "close",
        "iv",
        "delta",
        "gamma",
        "vega",
        "theta",
        "mid",
    )
    column_aliases: Mapping[str, str] = field(default_factory=dict)
    date_columns: Sequence[str] = ("expiry",)
    date_format: str = "%Y-%m-%d"


def normalize_dataframe(
    df: "pd.DataFrame",
    *,
    config: ChainNormalizerConfig | None = None,
    decimal_columns: Sequence[str] | None = None,
    column_aliases: Mapping[str, str] | None = None,
    date_columns: Sequence[str] | None = None,
    date_format: str | None = None,
) -> "pd.DataFrame":
    """Return ``df`` with normalised columns and number formats."""

    if pd is None:  # pragma: no cover - defensive guard
        raise RuntimeError("pandas is required to normalise dataframes")

    cfg = config or ChainNormalizerConfig()
    decimal_cols = tuple(decimal_columns or cfg.decimal_columns)
    aliases: Mapping[str, str] = {**cfg.column_aliases}
    if column_aliases:
        aliases = {**aliases, **column_aliases}
    date_cols = tuple(date_columns or cfg.date_columns)
    fmt = date_format or cfg.date_format

    return normalize_chain_dataframe(
        df,
        decimal_columns=decimal_cols,
        column_aliases=aliases,
        date_columns=date_cols,
        date_format=fmt,
    )


def normalize_chain_records(
    records: Iterable[Mapping[str, Any]],
    *,
    spot_price: float | None = None,
    interest_rate: float | None = None,
    apply_parity: bool = False,
    today_factory: Callable[[], Any] = today,
) -> list[dict[str, Any]]:
    """Return a normalised copy of ``records``.

    Numeric fields are coerced using :func:`normalize_leg`.  When
    ``apply_parity`` is ``True`` and a positive ``spot_price`` is supplied the
    helper will reconstruct missing mids via put-call parity.
    """

    normalized: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, Mapping):  # pragma: no cover - defensive
            continue
        normalized_record = normalize_leg(dict(record))
        normalized_record["mid_from_parity"] = bool(normalized_record.get("mid_from_parity"))
        normalized.append(normalized_record)

    if apply_parity and spot_price is not None and spot_price > 0 and normalized:
        rate = float(interest_rate) if interest_rate is not None else 0.03
        _apply_put_call_parity(
            normalized,
            spot=float(spot_price),
            interest_rate=rate,
            today_factory=today_factory,
        )

    return normalized


def _apply_put_call_parity(
    records: list[dict[str, Any]],
    *,
    spot: float,
    interest_rate: float,
    today_factory: Callable[[], Any],
) -> None:
    """Populate missing mids in ``records`` via put-call parity."""

    grouped: dict[tuple[str, float], dict[str, dict[str, Any]]] = {}

    for record in records:
        expiry_val = record.get("expiry") or record.get("expiration")
        strike_val = safe_float(record.get("strike"))
        if expiry_val in (None, "") or strike_val is None:
            continue
        right = get_leg_right(record)
        if right not in {"call", "put"}:
            continue
        key = (str(expiry_val), float(strike_val))
        grouped.setdefault(key, {})[right] = record

    if not grouped:
        return

    for (expiry, strike), pair in grouped.items():
        call = pair.get("call")
        put = pair.get("put")
        if not call or not put:
            continue

        call_mid = safe_float(call.get("mid"))
        put_mid = safe_float(put.get("mid"))
        if (call_mid is None) == (put_mid is None):
            continue

        dte = _determine_dte(call, put, expiry, today_factory)
        if dte is None:
            continue

        discount = strike * math.exp(-interest_rate * (dte / 365))
        if call_mid is None and put_mid is not None:
            new_mid = put_mid + spot - discount
            call["mid"] = round(new_mid, 4)
            call["mid_from_parity"] = True
            logger.debug(
                "[PARITY] Reconstructed mid for call @ %s (expiry %s) using put-call parity",
                strike,
                expiry,
            )
        elif put_mid is None and call_mid is not None:
            new_mid = call_mid - spot + discount
            put["mid"] = round(new_mid, 4)
            put["mid_from_parity"] = True
            logger.debug(
                "[PARITY] Reconstructed mid for put @ %s (expiry %s) using put-call parity",
                strike,
                expiry,
            )


def _determine_dte(
    call: Mapping[str, Any],
    put: Mapping[str, Any],
    expiry: Any,
    today_factory: Callable[[], Any],
) -> int | None:
    for record in (call, put):
        raw_dte = record.get("dte")
        if raw_dte is None:
            continue
        try:
            value = safe_float(raw_dte)
        except Exception:  # pragma: no cover - defensive
            value = None
        if value is None:
            continue
        try:
            return max(int(round(float(value))), 0)
        except Exception:  # pragma: no cover - defensive
            continue

    start = today_factory()
    try:
        return dte_between_dates(start, expiry)
    except Exception:  # pragma: no cover - defensive
        return None


__all__ = [
    "ChainNormalizerConfig",
    "dataframe_to_records",
    "normalize_chain_dataframe",
    "normalize_dataframe",
    "normalize_chain_records",
]
