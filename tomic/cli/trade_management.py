"""Trade management helper to show exit triggers for open positions.

This module loads positions and journal data, enriches the strategies with
PnL/DTE metrics and applies exit rules.  For each strategy a status is printed
indicating whether management is required and which triggers fired.
"""

from __future__ import annotations

from typing import Iterable, List

from tomic.analysis.strategy import group_strategies
from tomic.cli.strategy_dashboard import extract_exit_rules, generate_exit_alerts
from tomic.config import get as cfg_get
from tomic.journal.utils import load_json


def _filter_exit_alerts(alerts: Iterable[str]) -> List[str]:
    """Return only alerts related to exit rule triggers."""

    relevant = ["exitniveau", "PnL", "DTE ≤ exitdrempel"]
    return [a for a in alerts if any(key in a for key in relevant)]


def main() -> None:
    """Load trades, evaluate exit rules and print management status."""

    positions_file = cfg_get("POSITIONS_FILE", "positions.json")
    journal_file = cfg_get("JOURNAL_FILE", "journal.json")

    positions = load_json(positions_file)
    if not isinstance(positions, list):
        positions = []

    journal = load_json(journal_file)
    if not isinstance(journal, list):
        journal = []

    strategies = group_strategies(positions, journal)
    exit_rules = extract_exit_rules(journal_file)

    for strat in strategies:
        key = (strat.get("symbol"), strat.get("expiry"))
        rule = exit_rules.get(key)
        generate_exit_alerts(strat, rule)

        alerts = _filter_exit_alerts(strat.get("alerts", []))
        status = "⚠️ Beheer nodig" if alerts else "✅ Houden"
        exit_trigger = " | ".join(alerts) if alerts else "geen trigger"

        pnl = strat.get("unrealizedPnL")
        dte = strat.get("days_to_expiry")
        symbol = strat.get("symbol")
        expiry = strat.get("expiry")
        stype = strat.get("type")

        print(
            f"{symbol} {stype} {expiry} – PnL: {pnl} DTE: {dte} – "
            f"{status} – {exit_trigger}"
        )


if __name__ == "__main__":
    main()

