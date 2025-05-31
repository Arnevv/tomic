import json
from datetime import datetime
from typing import Dict, List

from tomic.logging import logger

from tomic.config import get as cfg_get
from tomic.logging import setup_logging
from tomic.utils import today


def apply_event_alerts(
    strategies: List[Dict], event_json_path: str = "events.json"
) -> None:
    """Add upcoming event alerts to strategies in place."""
    try:
        with open(event_json_path, "r", encoding="utf-8") as f:
            events = json.load(f)
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


def main(argv=None):
    setup_logging()
    logger.info("🚀 Event alerts check")
    if argv is None:
        argv = []
    strategies_file = argv[0] if argv else cfg_get("POSITIONS_FILE", "positions.json")

    from strategy_dashboard import group_strategies

    with open(strategies_file, "r", encoding="utf-8") as f:
        positions = json.load(f)
    strategies = group_strategies(positions)
    apply_event_alerts(strategies)
    for strat in strategies:
        alerts = strat.get("alerts", [])
        if alerts:
            logger.info("%s alerts:", strat["symbol"])
            for alert in alerts:
                logger.info(" - %s", alert)

    logger.success("✅ Events verwerkt")


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
