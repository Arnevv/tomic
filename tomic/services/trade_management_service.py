"""Domain service for trade management status aggregation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Sequence

from tomic.analysis.exit_rules import extract_exit_rules, generate_exit_alerts
from tomic.analysis.strategy import group_strategies
from tomic.config import get as cfg_get
from tomic.journal.utils import load_json


def _filter_exit_alerts(alerts: Iterable[str]) -> List[str]:
    relevant = ["exitniveau", "PnL", "DTE ≤ exitdrempel", "dagen in trade"]
    return [a for a in alerts if any(key in a for key in relevant)]


@dataclass(frozen=True)
class StrategyManagementSummary:
    """Reduced representation of the management status for a strategy."""

    symbol: str | None
    strategy: str | None
    spot: object
    unrealized_pnl: object
    days_to_expiry: object
    exit_trigger: str
    status: str


def build_management_summary(
    positions_file: str | None = None,
    journal_file: str | None = None,
    *,
    grouper=group_strategies,
    exit_rule_loader=extract_exit_rules,
    alert_generator=generate_exit_alerts,
    loader=load_json,
) -> Sequence[StrategyManagementSummary]:
    """Return strategy management statuses for the requested journal context."""

    positions_path = positions_file or cfg_get("POSITIONS_FILE", "positions.json")
    journal_path = journal_file or cfg_get("JOURNAL_FILE", "journal.json")

    positions = loader(positions_path)
    if not isinstance(positions, list):
        positions = []

    journal = loader(journal_path)
    if not isinstance(journal, list):
        journal = []

    strategies = grouper(positions, journal)
    exit_rules = exit_rule_loader(journal_path)

    summaries: list[StrategyManagementSummary] = []
    for strat in strategies:
        key = (strat.get("symbol"), strat.get("expiry"))
        rule = exit_rules.get(key)
        alert_generator(strat, rule)

        alerts = _filter_exit_alerts(strat.get("alerts", []))
        status = "⚠️ Beheer nodig" if alerts else "✅ Houden"
        exit_trigger = " | ".join(alerts) if alerts else "geen trigger"

        summaries.append(
            StrategyManagementSummary(
                symbol=strat.get("symbol"),
                strategy=strat.get("type"),
                spot=strat.get("spot"),
                unrealized_pnl=strat.get("unrealizedPnL"),
                days_to_expiry=strat.get("days_to_expiry"),
                exit_trigger=exit_trigger,
                status=status,
            )
        )

    return summaries


__all__ = ["StrategyManagementSummary", "build_management_summary"]

