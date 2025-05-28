import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from getonemarket import fetch_market_metrics


def store_volatility_snapshot(symbol_data: Dict, output_path: str = "volatility_data.json") -> None:
    """Append volatility snapshot to JSON file if complete."""
    required = ["date", "symbol", "spot", "iv30", "hv30", "iv_rank", "skew"]
    missing = [key for key in required if symbol_data.get(key) is None]
    if missing:
        logging.warning("Incomplete snapshot for %s skipped: missing %s", symbol_data.get("symbol"), ", ".join(missing))
        return

    file = Path(output_path)
    if file.exists():
        with open(file, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = []

    # Verwijder bestaande entry voor symbool + datum
    data = [
        d for d in data
        if not (d.get("symbol") == symbol_data["symbol"] and d.get("date") == symbol_data["date"])
    ]
    data.append(symbol_data)

    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def snapshot_symbols(symbols: List[str], output_path: str = "volatility_data.json") -> None:
    for sym in symbols:
        print(f"📈 Ophalen vol data voor {sym}")
        try:
            metrics = fetch_market_metrics(sym)
        except Exception as exc:
            print(f"⚠️ Mislukt voor {sym}: {exc}")
            continue
        record = {
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "symbol": sym,
            "spot": metrics.get("spot_price"),
            "iv30": metrics.get("implied_volatility"),
            "hv30": metrics.get("hv30"),
            "iv_rank": metrics.get("iv_rank"),
            "skew": metrics.get("skew"),
        }
        store_volatility_snapshot(record, output_path)
        print("✅ Snapshot opgeslagen")


def main(argv=None):
    if argv is None:
        argv = []
    if not argv:
        syms = input("Symbols kommagescheiden (bv. gld, xlf, xle, crm, aapl, tsla, qqq, dia, spy): ").upper().split(",")
        symbols = [s.strip() for s in syms if s.strip()]
    else:
        symbols = [a.upper() for a in argv]
    snapshot_symbols(symbols)


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
