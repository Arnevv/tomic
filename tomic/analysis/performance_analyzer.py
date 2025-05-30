import json
import logging
from statistics import mean
from typing import Dict, List, Optional

from tomic.utils import today
from tomic.logging import setup_logging
from tomic.journal.utils import load_journal
from tomic.helpers.account import _fmt_money

DEFAULT_JOURNAL_PATH = "journal.json"


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




def analyze(trades: List[dict]) -> Dict[str, dict]:
    """Compute stats per strategy type."""
    stats: Dict[str, dict] = {}
    grouped: Dict[str, List[float]] = {}

    for trade in trades:
        if not trade.get("DatumUit"):
            continue
        pnl = compute_pnl(trade)
        if pnl is None:
            logging.warning(
                "Onvolledige data voor trade %s, overslaan.", trade.get('TradeID')
            )
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
        logging.info("Geen afgesloten trades gevonden.")
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
            _fmt_money(data["avg_win"]),
            _fmt_money(data["avg_loss"]),
            _fmt_money(data["expectancy"]),
            _fmt_money(data["max_drawdown"]),
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
    print(
        f"\nBeste strategie: {best[0]} (expectancy {_fmt_money(best[1]['expectancy'])})"
    )
    print(
        f"Zwakste strategie: {worst[0]} (expectancy {_fmt_money(worst[1]['expectancy'])})"
    )


def main(argv=None) -> None:
    setup_logging()
    if argv is None:
        import sys
        argv = sys.argv[1:]

    journal_path = DEFAULT_JOURNAL_PATH
    json_output = None
    idx = 0
    if idx < len(argv) and not argv[0].startswith("--"):
        journal_path = argv[0]
        idx += 1

    if idx < len(argv) and argv[idx] == "--json-output" and idx + 1 < len(argv):
        json_output = argv[idx + 1]
        idx += 2

    if idx != len(argv):
        logging.error(
            "Gebruik: python performance_analyzer.py [journal_file] [--json-output PATH]"
        )
        return

    journal = load_journal(journal_path)
    stats = analyze(journal)
    if json_output:
        data = {
            "analysis_date": str(today()),
            "stats": stats,
        }
        with open(json_output, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    else:
        print_table(stats)


if __name__ == "__main__":
    import sys
    main(sys.argv[1:])
