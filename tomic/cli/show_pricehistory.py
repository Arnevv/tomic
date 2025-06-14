"""Display price history stored in the volatility database."""
from __future__ import annotations

from typing import List

from tomic.config import get as cfg_get
from tomic.analysis.vol_db import init_db
from tomic.logutils import setup_logging

try:
    from tabulate import tabulate
except Exception:  # pragma: no cover - fallback when tabulate missing

    def tabulate(rows: List[List[str]], headers: List[str] | None = None, tablefmt: str = "simple") -> str:
        if headers:
            table_rows = [headers] + rows
        else:
            table_rows = rows
        if not table_rows:
            return ""
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
    """Print historical prices for one or more symbols."""
    setup_logging()
    if argv is None:
        argv = []
    symbols = [s.upper() for s in argv] if argv else [s.upper() for s in cfg_get("DEFAULT_SYMBOLS", [])]

    conn = init_db(cfg_get("VOLATILITY_DB", "data/volatility.db"))
    try:
        for sym in symbols:
            cur = conn.execute(
                "SELECT date, close, volume, atr FROM PriceHistory WHERE symbol=? ORDER BY date",
                (sym,),
            )
            rows = cur.fetchall()
            if rows:
                print(f"\n=== {sym} ===")
                headers = ["date", "close", "volume", "atr"]
                print(tabulate(rows, headers=headers, tablefmt="github"))
            else:
                print(f"\n⚠️ Geen data gevonden voor {sym}")
    finally:
        conn.close()


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
