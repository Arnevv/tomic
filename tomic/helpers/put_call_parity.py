import logging

import pandas as pd

from tomic.core.data import normalize_chain_records

logger = logging.getLogger(__name__)


def fill_missing_mid_with_parity(df: pd.DataFrame, spot: float, r: float = 0.03) -> pd.DataFrame:
    """Return ``df`` with missing mids filled via put-call parity."""

    df = df.copy()
    if spot is None or df.empty:
        if "mid_from_parity" not in df.columns:
            df["mid_from_parity"] = False
        return df

    records = df.to_dict(orient="records")
    normalized = normalize_chain_records(
        records,
        spot_price=spot,
        interest_rate=r,
        apply_parity=True,
    )

    if "mid_from_parity" not in df.columns:
        df["mid_from_parity"] = False

    for idx, record in enumerate(normalized):
        if idx >= len(df.index):
            break
        df.at[df.index[idx], "mid"] = record.get("mid")
        df.at[df.index[idx], "mid_from_parity"] = bool(record.get("mid_from_parity"))

    return df

