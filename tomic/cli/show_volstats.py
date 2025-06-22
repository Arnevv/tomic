"""Display VolStats records from the volatility database."""

from __future__ import annotations

from typing import List

from tabulate import tabulate

from tomic.logutils import setup_logging
from tomic.config import get as cfg_get
from pathlib import Path
from tomic.journal.utils import load_json


def main(argv: List[str] | None = None) -> None:
    """Print recent volatility statistics."""
    setup_logging()
    limit = int(argv[0]) if argv else 20
    summary_dir = Path(cfg_get("IV_DAILY_SUMMARY_DIR", "tomic/data/iv_daily_summary"))
    hv_dir = Path(cfg_get("HISTORICAL_VOLATILITY_DIR", "tomic/data/historical_volatility"))

    rows = []
    for file in summary_dir.glob("*.json"):
        symbol = file.stem
        summaries = load_json(file)
        hvs = {r.get("date"): r for r in load_json(hv_dir / f"{symbol}.json")}
        if not isinstance(summaries, list):
            continue
        for rec in summaries:
            date = rec.get("date")
            hv_rec = hvs.get(date, {})
            rows.append([
                symbol,
                date,
                rec.get("atm_iv"),
                hv_rec.get("hv20"),
                hv_rec.get("hv30"),
                hv_rec.get("hv90"),
                rec.get("iv_rank"),
                rec.get("iv_percentile"),
            ])

    if not rows:
        print("⚠️ Geen volatiliteitsdata gevonden")
        return

    rows.sort(key=lambda r: (r[1], r[0]), reverse=True)
    rows = rows[:limit]
    headers = [
        "Symbol",
        "Date",
        "IV",
        "HV20",
        "HV30",
        "HV90",
        "Rank",
        "Pct",
    ]
    print(tabulate(rows, headers=headers, tablefmt="github"))


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
