import json
from loguru import logger
from pathlib import Path

from tomic.api.margin_calc import calculate_trade_margin
from tomic.logging import setup_logging
from tomic.config import get as cfg_get

JOURNAL_FILE = Path(cfg_get("JOURNAL_FILE", "journal.json"))


def update_all_margins() -> None:
    """Recalculate and store InitMargin for each trade in journal.json."""
    logger.info("🚀 Start margin update voor %s", JOURNAL_FILE)
    if not JOURNAL_FILE.exists():
        logger.error("⚠️ journal.json not found.")
        return

    with open(JOURNAL_FILE, "r", encoding="utf-8") as f:
        journal = json.load(f)

    updated_count = 0
    for trade in journal:
        sym = trade.get("Symbool")
        expiry = trade.get("Expiry")
        legs = trade.get("Legs")
        if not sym or not expiry or not legs:
            continue

        logger.info("🔄 Calculating margin for TradeID %s", trade.get('TradeID'))
        try:
            margin = calculate_trade_margin(sym, expiry, legs)
            trade["InitMargin"] = margin
            logger.info("   InitMargin → %s", margin)
            updated_count += 1
        except Exception as exc:
            logger.error("⚠️ Failed to calculate margin: %s", exc)

    if updated_count:
        with open(JOURNAL_FILE, "w", encoding="utf-8") as f:
            json.dump(journal, f, indent=2)
        logger.success("✅ Margins bijgewerkt voor %d trades.", updated_count)


if __name__ == "__main__":
    setup_logging()
    update_all_margins()

