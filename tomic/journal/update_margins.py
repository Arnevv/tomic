import json
from pathlib import Path

from tomic.api.margin_calc import calculate_trade_margin

JOURNAL_FILE = Path("journal.json")


def update_all_margins() -> None:
    """Recalculate and store InitMargin for each trade in journal.json."""
    if not JOURNAL_FILE.exists():
        print("⚠️ journal.json not found.")
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

        print(f"🔄 Calculating margin for TradeID {trade.get('TradeID')}")
        try:
            margin = calculate_trade_margin(sym, expiry, legs)
            trade["InitMargin"] = margin
            print(f"   InitMargin → {margin}")
            updated = True
        except Exception as exc:
            print(f"⚠️ Failed to calculate margin: {exc}")

    if updated:
        with open(JOURNAL_FILE, "w", encoding="utf-8") as f:
            json.dump(journal, f, indent=2)
        print("✅ journal.json updated with margins.")


if __name__ == "__main__":
    update_all_margins()
