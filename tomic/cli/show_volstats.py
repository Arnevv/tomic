"""Display VolStats records from the volatility database."""

from __future__ import annotations

from typing import List

from tabulate import tabulate

from tomic.logutils import setup_logging
from tomic.config import get as cfg_get
from tomic.analysis.vol_db import init_db


def main(argv: List[str] | None = None) -> None:
    """Print recent volatility statistics."""
    setup_logging()
    limit = int(argv[0]) if argv else 20
    conn = init_db(cfg_get("VOLATILITY_DB", "data/volatility.db"))
    try:
        cur = conn.execute(
            "SELECT symbol, date, iv, hv30, hv60, hv90, iv_rank, iv_percentile "
            "FROM VolStats ORDER BY date DESC, symbol LIMIT ?",
            (limit,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    if not rows:
        print("⚠️ Geen volatiliteitsdata gevonden")
        return
    headers = [
        "Symbol",
        "Date",
        "IV",
        "HV30",
        "HV60",
        "HV90",
        "Rank",
        "Pct",
    ]
    print(tabulate(rows, headers=headers, tablefmt="github"))


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
