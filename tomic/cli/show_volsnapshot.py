"""Display stored volatility snapshot for a given date."""
from __future__ import annotations

from datetime import datetime
from typing import List

from tomic.config import get as cfg_get
from tomic.analysis.vol_db import init_db
from tomic.logutils import setup_logging

try:
    from tabulate import tabulate
except Exception:  # pragma: no cover - fallback when tabulate missing

    def tabulate(
        rows: List[List[str]],
        headers: List[str] | None = None,
        tablefmt: str = "simple",
    ) -> str:
        if headers:
            table_rows = [headers] + rows
        else:
            table_rows = rows
        col_w = [max(len(str(c)) for c in col) for col in zip(*table_rows)]

        def fmt(row: List[str]) -> str:
            return "| " + " | ".join(str(c).ljust(col_w[i]) for i, c in enumerate(row)) + " |"

        lines = []
        if headers:
            lines.append(fmt(headers))
            lines.append("|-" + "-|-".join("-" * col_w[i] for i in range(len(col_w))) + "-|")
        for row in rows:
            lines.append(fmt(row))
        return "\n".join(lines)


def main(argv: List[str] | None = None) -> None:
    """Display VolStats rows for a given date."""
    setup_logging()
    if argv is None:
        argv = []
    date_str = argv[0] if argv else datetime.now().strftime("%Y-%m-%d")

    conn = init_db(cfg_get("VOLATILITY_DB", "data/volatility.db"))
    try:
        cur = conn.execute(
            "SELECT symbol, iv, hv30, hv60, hv90, iv_rank, iv_percentile "
            "FROM VolStats WHERE date=? ORDER BY symbol",
            (date_str,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    headers = ["symbol", "iv", "hv30", "hv60", "hv90", "iv_rank", "iv_percentile"]
    print(tabulate(rows, headers=headers, tablefmt="github"))


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
