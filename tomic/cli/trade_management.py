"""Trade management helper to show exit triggers for open positions."""

from __future__ import annotations

from tabulate import tabulate

from tomic.analysis.exit_rules import extract_exit_rules, generate_exit_alerts
from tomic.analysis.strategy import group_strategies
from tomic.config import get as cfg_get
from tomic.services.trade_management_service import build_management_summary


def main() -> None:
    """Load trades, evaluate exit rules and print management status."""

    positions_file = cfg_get("POSITIONS_FILE", "positions.json")
    journal_file = cfg_get("JOURNAL_FILE", "journal.json")

    summaries = build_management_summary(
        positions_file=positions_file,
        journal_file=journal_file,
        grouper=group_strategies,
        exit_rule_loader=extract_exit_rules,
        alert_generator=generate_exit_alerts,
    )

    print("=== 📊 TRADE MANAGEMENT ===")
    if not summaries:
        print("Geen strategieën gevonden.")
        return

    headers = [
        "#",
        "symbol",
        "strategy",
        "spot",
        "unrealizedPnL",
        "days_to_expiry",
        "exit_trigger",
        "status",
    ]

    rows: list[list[object]] = []
    for idx, summary in enumerate(summaries, start=1):
        rows.append(
            [
                idx,
                summary.symbol,
                summary.strategy,
                summary.spot,
                summary.unrealized_pnl,
                summary.days_to_expiry,
                summary.exit_trigger,
                summary.status,
            ]
        )

    print(tabulate(rows, headers=headers, tablefmt="plain"))


if __name__ == "__main__":
    main()

