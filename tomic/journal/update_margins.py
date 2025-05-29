import json
import logging
from pathlib import Path

from tomic.api.margin_calc import calculate_trade_margin
from tomic.logging import setup_logging

JOURNAL_FILE = Path("journal.json")


def update_all_margins() -> None:
    """Recalculate and store InitMargin for each trade in journal.json."""
    if not JOURNAL_FILE.exists():
        logging.error("⚠️ journal.json not found.")
        return

    with open(JOURNAL_FILE, "r", encoding="utf-8") as f:
        journal = json.load(f)

    updated = False
    for trade in journal:
        sym = trade.get("Symbool")
        expiry = trade.get("Expiry")
        legs = trade.get("Legs")
        if not sym or not expiry or not legs:
            continue

        logging.info("🔄 Calculating margin for TradeID %s", trade.get('TradeID'))
        try:
            margin = calculate_trade_margin(sym, expiry, legs)
            trade["InitMargin"] = margin
            logging.info("   InitMargin → %s", margin)
            updated = True
        except Exception as exc:
            logging.error("⚠️ Failed to calculate margin: %s", exc)

    if updated:
        with open(JOURNAL_FILE, "w", encoding="utf-8") as f:
            json.dump(journal, f, indent=2)
        logging.info("✅ journal.json updated with margins.")


if __name__ == "__main__":
    setup_logging()
    update_all_margins()
