import logging
import math
from typing import Optional

import pandas as pd

from .dateutils import dte_between_dates
from .timeutils import today

logger = logging.getLogger(__name__)


def fill_missing_mid_with_parity(df: pd.DataFrame, spot: float, r: float = 0.03) -> pd.DataFrame:
    """Return ``df`` with missing mids filled via put-call parity."""

    df = df.copy()
    if spot is None or df.empty:
        return df

    if "mid_from_parity" not in df.columns:
        df["mid_from_parity"] = False

    required_cols = {"expiration", "strike", "type", "mid"}
    if not required_cols.issubset(df.columns):
        return df

    for (exp, strike), grp in df.groupby(["expiration", "strike"]):
        if grp.shape[0] != 2:
            continue
        call_row = grp[grp["type"].str.lower().str.startswith("c")]
        put_row = grp[grp["type"].str.lower().str.startswith("p")]
        if call_row.empty or put_row.empty:
            continue
        call_idx = call_row.index[0]
        put_idx = put_row.index[0]
        call_mid = df.loc[call_idx, "mid"]
        put_mid = df.loc[put_idx, "mid"]

        missing_call = pd.isna(call_mid)
        missing_put = pd.isna(put_mid)
        if missing_call == missing_put:
            continue

        dte: Optional[int]
        if "dte" in grp.columns and pd.notna(grp["dte"].iloc[0]):
            try:
                dte = int(grp["dte"].iloc[0])
            except Exception:
                dte = None
        else:
            dte = dte_between_dates(today(), exp)

        if dte is None:
            continue

        T = dte / 365.0
        discount = strike * math.exp(-r * T)

        if missing_call:
            if pd.isna(put_mid):
                continue
            new_mid = float(put_mid) + spot - discount
            df.at[call_idx, "mid"] = round(new_mid, 4)
            df.at[call_idx, "mid_from_parity"] = True
            logger.info(
                f"[PARITY] Reconstructed mid for call @ {strike} (expiry {exp}) using put-call parity"
            )
        else:
            if pd.isna(call_mid):
                continue
            new_mid = float(call_mid) - spot + discount
            df.at[put_idx, "mid"] = round(new_mid, 4)
            df.at[put_idx, "mid_from_parity"] = True
            logger.info(
                f"[PARITY] Reconstructed mid for put @ {strike} (expiry {exp}) using put-call parity"
            )
    return df

