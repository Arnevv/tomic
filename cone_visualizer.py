import json
from datetime import datetime, timedelta
from typing import Tuple


def get_iv_percentile(symbol: str, snapshot_file: str, lookback_days: int = 365) -> Tuple[float, float, float, float, float]:
    with open(snapshot_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    today = datetime.utcnow().date()
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
        if (today - dt).days <= lookback_days:
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


def display_cone(symbol: str, snapshot_file: str = "volatility_data.json") -> None:
    try:
        iv, pct, p10, p50, p90 = get_iv_percentile(symbol, snapshot_file)
    except Exception as exc:
        print(f"⚠️ {exc}")
        return
    print(f"{symbol} – IV30: {iv:.2%} ({pct:.0f}e percentiel)")
    print(f"Historische range: P10={p10:.2%} P50={p50:.2%} P90={p90:.2%}")


def main(argv=None):
    if argv is None:
        argv = []
    symbol = argv[0].upper() if argv else input("Symbol: ").strip().upper()
    display_cone(symbol)


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
