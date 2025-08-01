"""Attach event alerts to strategies."""

from datetime import datetime
from typing import Dict, List

from tomic.logutils import logger

from tomic.config import get as cfg_get
from tomic.logutils import setup_logging
from tomic.utils import today
from tomic.journal.utils import load_json


def apply_event_alerts(
    strategies: List[Dict], event_json_path: str = "events.json"
) -> None:
    """Add upcoming event alerts to strategies in place."""
    try:
        events = load_json(event_json_path)
    except FileNotFoundError:
        return

    today_date = today()

    for evt in events:
        sym = evt.get("symbol")
        date_str = evt.get("date")
        label = evt.get("label") or evt.get("type")
        if not sym or not date_str:
            continue
        try:
            evt_date = datetime.fromisoformat(date_str).date()
        except ValueError:
            continue
        days = (evt_date - today_date).days
        if days < 0 or days > 7:
            continue
        for strat in strategies:
            if strat.get("symbol") != sym:
                continue
            msg = f"{sym} heeft {label} over {days} dagen"
            strat.setdefault("alerts", []).append(msg)


def main(argv: List[str] | None = None) -> None:
    """Load strategies and log upcoming events."""
    setup_logging()
    logger.info("🚀 Event alerts check")
    if argv is None:
        argv = []
    strategies_file = argv[0] if argv else cfg_get("POSITIONS_FILE", "positions.json")

    from tomic.analysis.strategy import group_strategies

    positions = load_json(strategies_file)
    strategies = group_strategies(positions)
    apply_event_alerts(strategies)
    for strat in strategies:
        alerts = strat.get("alerts", [])
        if alerts:
            logger.info(f"{strat['symbol']} alerts:")
            for alert in alerts:
                logger.info(f" - {alert}")

    logger.success("✅ Events verwerkt")


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
