import json
from pathlib import Path

from tomic.logutils import logger

from tomic.api.margin_calc import calculate_trade_margin
from tomic.logutils import setup_logging
from tomic.config import get as cfg_get

JOURNAL_FILE = Path(cfg_get("JOURNAL_FILE", "journal.json"))


def update_all_margins() -> None:
    """Recalculate and store InitMargin for each trade in journal.json."""
    logger.info(f"🚀 Start margin update voor {JOURNAL_FILE}")
    if not JOURNAL_FILE.exists():
        logger.error("⚠️ journal.json not found.")
        return

    try:
        with open(JOURNAL_FILE, "r", encoding="utf-8") as f:
            journal = json.load(f)
    except json.JSONDecodeError as exc:
        logger.error(f"⚠️ Invalid JSON in journal file: {exc}")
        return
    except OSError as exc:
        logger.error(f"⚠️ Could not read journal file: {exc}")
        return

    if not isinstance(journal, list):
        logger.error("⚠️ Journal file does not contain a list")
        return

    updated_count = 0
    for trade in journal:
        sym = trade.get("Symbool")
        expiry = trade.get("Expiry")
        legs = trade.get("Legs")
        if not sym or not expiry or not legs:
            continue

        logger.info(f"🔄 Calculating margin for TradeID {trade.get('TradeID')}")
        try:
            margin = calculate_trade_margin(sym, expiry, legs)
            trade["InitMargin"] = margin
            logger.info(f"   InitMargin → {margin}")
            updated_count += 1
        except Exception as exc:
            logger.error(f"⚠️ Failed to calculate margin: {exc}")

    if updated_count:
        try:
            with open(JOURNAL_FILE, "w", encoding="utf-8") as f:
                json.dump(journal, f, indent=2)
            logger.success(f"✅ Margins bijgewerkt voor {updated_count} trades.")
        except OSError as exc:
            logger.error(f"⚠️ Could not write journal file: {exc}")


if __name__ == "__main__":
    setup_logging()
    update_all_margins()
