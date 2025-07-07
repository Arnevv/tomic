"""Display upcoming earnings information with volatility metrics."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import List

from tomic.config import get as cfg_get
from tomic.journal.utils import load_json
from tomic.utils import today

try:
    from tabulate import tabulate
except Exception:  # pragma: no cover - fallback when tabulate is missing

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


def _load_iv_data(symbol: str, directory: Path) -> dict[str, dict]:
    data = load_json(directory / f"{symbol}.json")
    if not isinstance(data, list):
        return {}
    return {rec.get("date"): rec for rec in data if isinstance(rec, dict)}


def _most_recent_iv_record(
    iv_data: dict[str, dict], today_str: str
) -> tuple[str | None, dict | None]:
    """Zoek meest recente IV-record ≤ ``today_str``."""

    dates = sorted(iv_data.keys(), reverse=True)
    for d in dates:
        if d <= today_str:
            return d, iv_data[d]
    return None, None


def _next_earnings(symbol: str, earnings: dict[str, list[str]]) -> tuple[str | None, int | None]:
    dates = earnings.get(symbol)
    if not isinstance(dates, list):
        return None, None
    today_dt = today()
    selected: datetime | None = None
    for ds in dates:
        try:
            ed = datetime.strptime(ds, "%Y-%m-%d").date()
        except Exception:
            continue
        dte = (ed - today_dt).days
        if -1 <= dte <= 10:
            selected = ed
            break
    if selected is None:
        return None, None
    return selected.strftime("%Y-%m-%d"), (selected - today_dt).days


def _historical_iv_delta(symbol: str, dte: int, earnings: dict[str, list[str]], iv_by_date: dict[str, dict]) -> float | None:
    dates = earnings.get(symbol)
    if not isinstance(dates, list) or dte is None:
        return None
    vals: list[float] = []
    for ds in dates:
        try:
            ed = datetime.strptime(ds, "%Y-%m-%d").date()
        except Exception:
            continue
        if ed >= today():
            continue
        start = ed - timedelta(days=dte)
        iv_start = iv_by_date.get(start.strftime("%Y-%m-%d"), {}).get("atm_iv")
        iv_end = iv_by_date.get(ed.strftime("%Y-%m-%d"), {}).get("atm_iv")
        if iv_start is None or iv_end is None:
            continue
        if iv_start == 0:
            continue
        vals.append((iv_end - iv_start) / iv_start)
    if not vals:
        return None
    return sum(vals) / len(vals)


def main(argv: List[str] | None = None) -> None:
    """Print earnings overview table."""
    if argv is None:
        argv = []
    symbols = [s.upper() for s in argv] if argv else [s.upper() for s in cfg_get("DEFAULT_SYMBOLS", [])]

    summary_dir = Path(cfg_get("IV_DAILY_SUMMARY_DIR", "tomic/data/iv_daily_summary"))
    earnings_file = Path(cfg_get("EARNINGS_DATES_FILE", "tomic/data/earnings_dates.json"))
    earnings_data = load_json(earnings_file)
    if not isinstance(earnings_data, dict):
        earnings_data = {}

    rows: list[dict[str, object]] = []
    warnings: list[str] = []
    today_str = today().strftime("%Y-%m-%d")

    for sym in symbols:
        iv_data = _load_iv_data(sym, summary_dir)
        iv_date_used, iv_today_rec = _most_recent_iv_record(iv_data, today_str)
        if iv_today_rec is None:
            continue  # geen bruikbare data beschikbaar
        iv_age = (
            today() - datetime.strptime(iv_date_used, "%Y-%m-%d").date()
        ).days
        earn_date, dte = _next_earnings(sym, earnings_data)
        if earn_date is None or dte is None:
            continue
        iv_today_val = iv_today_rec.get("atm_iv")
        iv_rank_val = iv_today_rec.get("iv_rank (HV)")
        iv_delta = _historical_iv_delta(sym, dte, earnings_data, iv_data)
        proj_iv = None
        if iv_today_val is not None and iv_delta is not None:
            proj_iv = iv_today_val * (1 + iv_delta)
        # Determine strategy
        strat = "—"
        if dte >= 10 and (iv_delta or 0) >= 0.10:
            strat = "Calendar \U0001F4C6"
        elif 3 <= dte <= 9 and (iv_delta or 0) >= 0.05:
            strat = "Ratio \u2696\uFE0F"
        elif -1 <= dte <= 0:
            strat = "Iron Condor \U0001F916"
        rows.append(
            {
                "symbol": sym,
                "earnings_date": earn_date,
                "dte": dte,
                "iv_rank": iv_rank_val,
                "iv_today": iv_today_val,
                "iv_date_used": iv_date_used,
                "iv_delta": iv_delta,
                "projected_iv": proj_iv,
                "strategie": strat,
            }
        )
        if iv_age > 2:
            warnings.append(
                f"\u26A0\ufe0f Waarschuwing: IV-data voor {sym} is {iv_age} dagen oud (laatst op {iv_date_used})"
            )

    if not rows:
        print("Geen earnings binnen 10 dagen gevonden.")
        return

    rows.sort(key=lambda r: r["dte"])  # sort by days to earnings

    table_rows: list[list[str]] = []
    for idx, r in enumerate(rows, 1):
        dte_str = f"{r['dte']:+d}" if isinstance(r.get("dte"), int) else ""
        iv_rank = r.get("iv_rank")
        iv_rank_str = f"{iv_rank:.0f}%" if isinstance(iv_rank, (int, float)) else ""
        iv_today = r.get("iv_today")
        iv_today_str = f"{iv_today:.3f}" if isinstance(iv_today, (int, float)) else ""
        iv_date_used = r.get("iv_date_used")
        iv_today_date_str = f"{iv_date_used[5:]}" if iv_date_used else ""
        iv_delta = r.get("iv_delta")
        iv_delta_str = f"{iv_delta*100:+.1f}%" if isinstance(iv_delta, (int, float)) else ""
        proj = r.get("projected_iv")
        proj_str = f"{proj:.3f}" if isinstance(proj, (int, float)) else "—"
        table_rows.append(
            [
                idx,
                r["symbol"],
                r["earnings_date"],
                dte_str,
                iv_rank_str,
                f"{iv_today_str} ({iv_today_date_str})",
                iv_delta_str,
                proj_str,
                r["strategie"],
            ]
        )

    headers = [
        "Nr",
        "Symbool",
        "Earnings op",
        "Dagen tot",
        "IV Rank",
        "Huidige IV (op)",
        "IV \u0394 @ -DTE",
        "Projected IV",
        "Strategie",
    ]

    print(f"\n6. Earnings-informatie")
    print(f"Laatst bijgewerkt: {today_str}\n")
    print(tabulate(table_rows, headers=headers, tablefmt="github"))
    for msg in warnings:
        print(msg)

    _ = input("Voer het nummer in om dit symbool te analyseren \u2192 ")
    print("Moet nog uitgewerkt worden")


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
