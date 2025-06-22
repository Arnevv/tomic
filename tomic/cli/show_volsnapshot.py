"""Display stored volatility snapshot for a given date."""
from __future__ import annotations

from datetime import datetime
from typing import List

from tomic.config import get as cfg_get
from pathlib import Path
from tomic.journal.utils import load_json
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

    summary_dir = Path(cfg_get("IV_DAILY_SUMMARY_DIR", "tomic/data/iv_daily_summary"))
    hv_dir = Path(cfg_get("HISTORICAL_VOLATILITY_DIR", "tomic/data/historical_volatility"))

    rows = []
    for file in summary_dir.glob("*.json"):
        symbol = file.stem
        summaries = [r for r in load_json(file) if r.get("date") == date_str]
        hvs = {r.get("date"): r for r in load_json(hv_dir / f"{symbol}.json")}
        for rec in summaries:
            hv_rec = hvs.get(date_str, {})
            rows.append([
                symbol,
                rec.get("atm_iv"),
                hv_rec.get("hv20"),
                hv_rec.get("hv30"),
                hv_rec.get("hv90"),
                rec.get("iv_rank"),
                rec.get("iv_percentile"),
            ])

    headers = ["symbol", "iv", "hv20", "hv30", "hv90", "iv_rank", "iv_percentile"]
    print(tabulate(rows, headers=headers, tablefmt="github"))


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
