"""Utilities for interpolating missing option chain fields."""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from scipy.interpolate import UnivariateSpline

logger = logging.getLogger(__name__)


def interpolate_missing_fields(df: pd.DataFrame) -> pd.DataFrame:
    """Fill missing ``delta`` and ``iv`` fields in ``df``.

    Interpolation happens per expiry and option ``type`` to avoid mixing call and
    put data. Both ``expiry`` and ``expiration`` column names are supported. If
    ``expiration`` is present but ``expiry`` is not, it is used transparently
    without creating an additional column.

    ``delta`` values are linearly interpolated while ``iv`` values are spline
    interpolated. If IV values appear to be in percentage format (> 3.0) they are
    converted to decimals before interpolation.
    """

    df = df.copy()
    logger.info("Interpolating delta (linear) and iv (spline) per expiry/type")

    expiry_col = "expiry" if "expiry" in df.columns else "expiration" if "expiration" in df.columns else None
    if expiry_col is None:
        raise KeyError("DataFrame must contain 'expiry' or 'expiration' column")

    result_frames: list[pd.DataFrame] = []

    group_cols = [expiry_col]
    if "type" in df.columns:
        group_cols.append("type")

    for key, group in df.groupby(group_cols):
        if isinstance(key, tuple):
            exp = key[0]
            opt_type = key[1] if len(key) > 1 else None
        else:
            exp = key
            opt_type = None
        g = group.copy()

        # Ensure numeric strikes for interpolation
        g["strike"] = pd.to_numeric(g["strike"], errors="coerce")
        g = g.dropna(subset=["strike"])

        if g.empty:
            continue

        # Detect percentage scale for IV and normalise to decimals
        if "iv" in g.columns and g["iv"].notna().any():
            max_iv = g["iv"].dropna().max()
            if max_iv > 3.0:
                logger.info(
                    f"IV appears to be in % scale – converting by dividing by 100 for ({exp}, {opt_type})"
                )
                g["iv"] = g["iv"] / 100

        if "delta" in g.columns:
            g["delta"] = _interpolate_column(g, column="delta", method="linear")
            g["delta"] = g["delta"].clip(lower=-1.0, upper=1.0)

        if "iv" in g.columns:
            g["iv"] = _interpolate_column(g, column="iv", method="spline")
            g["iv"] = g["iv"].clip(lower=0.01, upper=5.0)
            logger.info("Clipped interpolated IV to [0.01, 5.0]")

        result_frames.append(g)

    return pd.concat(result_frames, ignore_index=True)


def _interpolate_column(group: pd.DataFrame, column: str, method: str) -> pd.Series:
    x = group['strike']
    y = group[column]

    if y.isnull().sum() == 0:
        return y  # niets te interpoleren

    if method == 'linear':
        valid = y.notnull()
        if valid.sum() < 2:
            return y  # onvoldoende punten voor lineaire interpolatie
        return pd.Series(np.interp(x, x[valid], y[valid]), index=group.index)

    elif method == 'spline':
        valid = y.notnull()
        if valid.sum() < 4:
            return y  # onvoldoende punten voor spline

        x_valid = pd.Series(x[valid]).astype(float)
        y_valid = pd.Series(y[valid]).astype(float)
        df_valid = (
            pd.DataFrame({"x": x_valid, "y": y_valid})
            .sort_values("x")
            .groupby("x", as_index=False)
            .mean()
        )
        if len(df_valid) < 4:
            return y

        spline = UnivariateSpline(df_valid["x"], df_valid["y"], s=0)
        x_all = pd.Series(x).astype(float)
        return pd.Series(spline(x_all), index=group.index)

    else:
        raise ValueError(f"Unsupported interpolation method: {method}")

