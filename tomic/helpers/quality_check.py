import pandas as pd
from tomic.utils import get_option_mid_price


def calculate_csv_quality(df: pd.DataFrame) -> float:
    """Return partial quality percentage for option chain DataFrame."""
    if df.empty:
        return 0.0

    required_cols = [
        "bid",
        "ask",
        "close",
        "iv",
        "delta",
        "gamma",
        "vega",
        "theta",
    ]
    for col in required_cols:
        if col not in df.columns:
            df[col] = None

    def _score(row: pd.Series) -> int:
        score = 0
        price, _ = get_option_mid_price(row.to_dict())
        if price is not None:
            score += 2
        try:
            if row["iv"] != "" and row["iv"] is not None:
                float(row["iv"])
                score += 2
        except Exception:
            pass
        try:
            if row["delta"] != "" and row["delta"] is not None:
                d = float(row["delta"])
                if -1.0 <= d <= 1.0:
                    score += 2
        except Exception:
            pass
        for col in ["gamma", "vega", "theta"]:
            try:
                val = row[col]
                if val != "" and val is not None:
                    float(val)
                    score += 1
            except Exception:
                pass
        return score

    total_score = sum(_score(row) for _, row in df.iterrows())
    max_score = len(df) * 9
    return (total_score / max_score) * 100 if max_score else 0.0

