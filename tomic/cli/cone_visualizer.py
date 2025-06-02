"""Visualize volatility cone percentiles for a symbol."""

from datetime import datetime
from typing import List, Tuple

from tomic.config import get as cfg_get
from tomic.utils import today
from tomic.journal.utils import load_json


def get_iv_percentile(symbol: str, snapshot_file: str, lookback_days: int = 365) -> Tuple[float, float, float, float, float]:
    data = load_json(snapshot_file)
    today_date = today()

    entries = [
        d for d in data
        if d.get("symbol") == symbol and
        "iv30" in d and d.get("date")
    ]
    filtered = []
    for d in entries:
        try:
            dt = datetime.fromisoformat(d["date"]).date()
        except ValueError:
            continue
        if (today_date - dt).days <= lookback_days:
            filtered.append((dt, d["iv30"]))
    if not filtered:
        raise ValueError("No data for symbol")
    filtered.sort(key=lambda x: x[0])
    iv_values = [v for _, v in filtered if v is not None]
    if not iv_values:
        raise ValueError("No IV30 values")
    latest_iv = iv_values[-1]
    sorted_vals = sorted(iv_values)
    rank = sorted_vals.index(latest_iv)
    percentile = (rank / len(sorted_vals)) * 100
    p10 = sorted_vals[int(0.1 * (len(sorted_vals)-1))]
    p50 = sorted_vals[int(0.5 * (len(sorted_vals)-1))]
    p90 = sorted_vals[int(0.9 * (len(sorted_vals)-1))]
    return latest_iv, percentile, p10, p50, p90


def display_cone(symbol: str, snapshot_file: str | None = None) -> None:
    """Print current IV rank and historical percentiles for ``symbol``."""
    if snapshot_file is None:
        snapshot_file = cfg_get("VOLATILITY_DATA_FILE", "volatility_data.json")
    try:
        iv, pct, p10, p50, p90 = get_iv_percentile(symbol, snapshot_file)
    except Exception as exc:
        print(f"⚠️ {exc}")
        return
    print(f"{symbol} – IV30: {iv:.2%} ({pct:.0f}e percentiel)")
    print(f"Historische range: P10={p10:.2%} P50={p50:.2%} P90={p90:.2%}")


def main(argv: List[str] | None = None) -> None:
    """Entry point for CLI usage."""
    if argv is None:
        argv = []
    symbol = argv[0].upper() if argv else input("Symbol: ").strip().upper()
    display_cone(symbol)


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
