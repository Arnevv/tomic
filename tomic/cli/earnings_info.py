"""Display upcoming earnings information with volatility metrics."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import List

from tomic.config import get as cfg_get
from tomic.journal.utils import load_json
from tomic.utils import today
from tomic.cli.volatility_recommender import recommend_strategies

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


def _load_hv_data(symbol: str, directory: Path) -> dict[str, dict]:
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


def _next_earnings(symbol: str, earnings: list[dict]) -> tuple[str | None, int | None]:
    today_dt = today()
    selected: datetime | None = None
    for rec in earnings:
        if rec.get("symbol") != symbol:
            continue
        try:
            ed = datetime.strptime(rec.get("date", ""), "%Y-%m-%d").date()
        except Exception:
            continue
        dte = (ed - today_dt).days
        if -1 <= dte <= 10:
            selected = ed
            break
    if selected is None:
        return None, None
    return selected.strftime("%Y-%m-%d"), (selected - today_dt).days


def historical_hv_delta(
    symbol: str,
    dte: int,
    earnings_data: list[dict],
    hv_by_date: dict[str, dict],
) -> float | None:
    if dte is None:
        return None
    today_dt = today()
    deltas: list[float] = []
    for rec in earnings_data:
        if rec.get("symbol") != symbol:
            continue
        try:
            ed = datetime.strptime(rec.get("date", ""), "%Y-%m-%d").date()
        except Exception:
            continue
        if ed >= today_dt:
            continue
        start_date = ed - timedelta(days=dte)
        hv_start = None
        hv_end = None
        for off in (-1, 0, 1):
            hv = hv_by_date.get((start_date + timedelta(days=off)).strftime("%Y-%m-%d"))
            if hv is not None and hv_start is None:
                hv_start = hv.get("hv20")
        for off in (-1, 0, 1):
            hv = hv_by_date.get((ed + timedelta(days=off)).strftime("%Y-%m-%d"))
            if hv is not None and hv_end is None:
                hv_end = hv.get("hv20")
        if hv_start is None or hv_end is None:
            continue
        if hv_start == 0:
            continue
        deltas.append((hv_end - hv_start) / hv_start)
    if len(deltas) < 2:
        return None
    return sum(deltas) / len(deltas)


def main(argv: List[str] | None = None) -> None:
    """Print earnings overview table."""
    if argv is None:
        argv = []
    symbols = [s.upper() for s in argv] if argv else [s.upper() for s in cfg_get("DEFAULT_SYMBOLS", [])]

    summary_dir = Path(cfg_get("IV_DAILY_SUMMARY_DIR", "tomic/data/iv_daily_summary"))
    earnings_file = Path(cfg_get("EARNINGS_DATES_FILE", "tomic/data/earnings_dates.json"))
    earnings_dict = load_json(earnings_file)
    earnings_data: list[dict] = []
    if isinstance(earnings_dict, dict):
        for symbol, dates in earnings_dict.items():
            if isinstance(dates, list):
                for date_str in dates:
                    earnings_data.append({"symbol": symbol, "date": date_str})

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
        hv_data = _load_hv_data(sym, Path(cfg_get("HISTORICAL_VOLATILITY_DIR", "tomic/data/historical_volatility")))
        earn_date, dte = _next_earnings(sym, earnings_data)
        if earn_date is None or dte is None:
            continue
        iv_today_val = iv_today_rec.get("atm_iv")
        iv_rank_val = iv_today_rec.get("iv_rank (HV)")
        if isinstance(iv_rank_val, (int, float)) and iv_rank_val > 1:
            iv_rank_val /= 100
        hv_delta = historical_hv_delta(sym, dte, earnings_data, hv_data)
        proj_iv = None
        if hv_delta is not None and iv_today_val is not None:
            proj_iv = iv_today_val * (1 + hv_delta)

        recs = recommend_strategies(
            {
                "symbol": sym,
                "iv_rank": iv_rank_val,
                "iv": iv_today_val,
                "hv_delta": hv_delta,
                "term_structure": None,
                "skew": None,
                "dte": dte,
            }
        )
        strat = recs[0]["strategy"] if recs else "—"
        rows.append(
            {
                "symbol": sym,
                "earnings_date": earn_date,
                "dte": dte,
                "iv_rank": iv_rank_val,
                "iv_today": iv_today_val,
                "iv_date_used": iv_date_used,
                "hv_delta": hv_delta,
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
        iv_rank_str = (
            f"{iv_rank * 100:.0f}%" if isinstance(iv_rank, (int, float)) else ""
        )
        iv_today = r.get("iv_today")
        iv_today_str = f"{iv_today:.3f}" if isinstance(iv_today, (int, float)) else ""
        iv_date_used = r.get("iv_date_used")
        iv_today_date_str = f"{iv_date_used[5:]}" if iv_date_used else ""
        hv_delta_val = r.get("hv_delta")
        if isinstance(hv_delta_val, (int, float)):
            iv_delta_str = f"{hv_delta_val*100:+.1f}% (gebaseerd op hv20)"
        else:
            iv_delta_str = ""
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

    sel = input("Voer het nummer in om dit symbool te analyseren \u2192 ").strip()
    try:
        idx = int(sel) - 1
        chosen = rows[idx]
    except Exception:
        return

    sym = chosen.get("symbol")
    print(f"\n=== \U0001F4CA Earningsanalyse voor {sym} ===")
    edate = chosen.get("earnings_date")
    dte = chosen.get("dte")
    print(f"Earningsdatum    : {edate} (DTE = {dte})")
    iv_today = chosen.get("iv_today")
    iv_date_used = chosen.get("iv_date_used")
    iv_str = f"{iv_today:.3f}" if isinstance(iv_today, (int, float)) else "—"
    iv_date_str = f"{iv_date_used[5:]}" if iv_date_used else ""
    print(f"Huidige IV       : {iv_str} ({iv_date_str})")
    ivr = chosen.get("iv_rank")
    ivr_str = f"{ivr * 100:.0f}%" if isinstance(ivr, (int, float)) else "—"
    print(f"IV Rank          : {ivr_str}")
    hvd = chosen.get("hv_delta")
    hvd_str = f"{hvd*100:+.1f}%" if isinstance(hvd, (int, float)) else "—"
    print(f"HV-delta (hv20)  : {hvd_str}")
    proj = chosen.get("projected_iv")
    proj_str = f"{proj:.3f}" if isinstance(proj, (int, float)) else "—"
    print(f"Projected IV     : {proj_str}")

    recs = recommend_strategies(
        {
            "symbol": sym,
            "iv_rank": ivr,
            "iv": iv_today,
            "hv_delta": hvd,
            "term_structure": None,
            "skew": None,
            "dte": dte,
        }
    )
    strat = recs[0]["strategy"] if recs else "—"
    print(f"Strategieadvies  : {strat}")
    if recs:
        print("\n\U0001F4D8 Strategie\u00ebn volgens volatility_rules.yaml:")
        for r in recs:
            reason = r.get("indication") or ""
            print(f"- {r.get('strategy')} \u2192 reden: {reason}")

    print("\n⚠️ De option chain is nog niet opgehaald.")
    print("Kies [C] om de chain op te halen en strategievoorstellen te genereren")
    print("Kies [Q] om terug te keren")

    choice = input("→ ").strip().lower()
    if choice.startswith("c"):
        print("Chain ophalen via Control Panel is nog niet geïntegreerd.")


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
