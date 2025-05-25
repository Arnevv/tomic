import json
from pathlib import Path
from statistics import mean
from typing import Dict, List, Optional

JOURNAL_PATH = Path("journal.json")


def load_journal() -> List[dict]:
    """Load journal.json and return list of trades."""
    if not JOURNAL_PATH.exists():
        print("⚠️ Geen journal.json gevonden.")
        return []
    with JOURNAL_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def compute_pnl(trade: dict) -> Optional[float]:
    """Return profit/loss for trade or None if not determinable."""
    if trade.get("Resultaat") is not None:
        try:
            return float(trade["Resultaat"])
        except (TypeError, ValueError):
            return None

    try:
        entry = trade.get("EntryPrice")
        exit_p = trade.get("ExitPrice")
        if entry is not None and exit_p is not None:
            return (float(entry) - float(exit_p)) * 100
    except (TypeError, ValueError):
        return None

    try:
        premium = trade.get("Premium")
        exit_p = trade.get("ExitPrice")
        if premium is not None and exit_p is not None:
            return (float(premium) - float(exit_p)) * 100
    except (TypeError, ValueError):
        return None
    return None


def fmt_money(value: float) -> str:
    """Format float as signed dollar value without decimals."""
    if value > 0:
        return f"+${value:.0f}"
    if value < 0:
        return f"–${abs(value):.0f}"
    return "±$0"


def analyze(trades: List[dict]) -> Dict[str, dict]:
    """Compute stats per strategy type."""
    stats: Dict[str, dict] = {}
    grouped: Dict[str, List[float]] = {}

    for trade in trades:
        if not trade.get("DatumUit"):
            continue
        pnl = compute_pnl(trade)
        if pnl is None:
            print(f"⚠️ Onvolledige data voor trade {trade.get('TradeID')}, overslaan.")
            continue
        t_type = trade.get("Type") or "Onbekend"
        grouped.setdefault(t_type, []).append(pnl)

    for t_type, pnls in grouped.items():
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        count = len(pnls)
        winrate = len(wins) / count if count else 0
        avg_win = mean(wins) if wins else 0.0
        avg_loss = mean(losses) if losses else 0.0
        expectancy = winrate * avg_win + (1 - winrate) * avg_loss
        max_drawdown = min(pnls)
        stats[t_type] = {
            "trades": count,
            "winrate": winrate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "expectancy": expectancy,
            "max_drawdown": max_drawdown,
        }
    return stats


def print_table(stats: Dict[str, dict]) -> None:
    if not stats:
        print("Geen afgesloten trades gevonden.")
        return

    headers = [
        "Strategie",
        "Trades",
        "Winrate",
        "Avg Win",
        "Avg Loss",
        "Expectancy",
        "Max Drawdown",
    ]
    col_widths = [len(h) for h in headers]

    rows = []
    for strat, data in stats.items():
        row = [
            strat,
            str(data["trades"]),
            f"{data['winrate']*100:.0f}%",
            fmt_money(data["avg_win"]),
            fmt_money(data["avg_loss"]),
            fmt_money(data["expectancy"]),
            fmt_money(data["max_drawdown"]),
        ]
        rows.append(row)
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    header_line = "| " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"
    sep_line = "| " + " | ".join("-" * col_widths[i] for i in range(len(headers))) + " |"
    print("=== Strategie Performance (afgelopen 90 dagen) ===")
    print(header_line)
    print(sep_line)
    for row in rows:
        print("| " + " | ".join(row[i].ljust(col_widths[i]) for i in range(len(headers))) + " |")

    # summary
    best = max(stats.items(), key=lambda x: x[1]["expectancy"])
    worst = min(stats.items(), key=lambda x: x[1]["expectancy"])
    print(f"\nBeste strategie: {best[0]} (expectancy {fmt_money(best[1]['expectancy'])})")
    print(f"Zwakste strategie: {worst[0]} (expectancy {fmt_money(worst[1]['expectancy'])})")


def main() -> None:
    journal = load_journal()
    stats = analyze(journal)
    print_table(stats)


if __name__ == "__main__":
    main()
