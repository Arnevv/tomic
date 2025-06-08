"""Interactive helper to close a trade in the journal."""

from datetime import datetime
from typing import Any, Dict

from tomic.logutils import logger

from tomic.logutils import setup_logging
from tomic.journal.service import (
    load_journal,
    update_trade,
    is_valid_trade_id,
)
from .common import prompt


def sluit_trade_af(trade: Dict[str, Any]) -> None:
    """Interactively enter exit details for ``trade``."""
    logger.info(
        f"\n🔚 Trade afsluiten: {trade['TradeID']} - {trade['Symbool']} - {trade['Type']}"
    )

    # DatumUit en DaysInTrade
    datum_uit = prompt("📆 DatumUit (YYYY-MM-DD): ")
    try:
        d_in = datetime.strptime(trade["DatumIn"], "%Y-%m-%d")
        d_out = datetime.strptime(datum_uit, "%Y-%m-%d")
        trade["DatumUit"] = datum_uit
        trade["DaysInTrade"] = (d_out - d_in).days
        logger.info(f"📅 DaysInTrade berekend: {trade['DaysInTrade']} dagen")
    except Exception:
        logger.error("⚠️ Ongeldige datum. Sla DaysInTrade over.")
        trade["DatumUit"] = datum_uit

    # ExitPrice met EntryPrice ter referentie
    try:
        entry_price = trade.get("EntryPrice", "?")
        exit_price_input = prompt(f"💰 Exitprijs (de entry prijs was: {entry_price}): ")
        trade["ExitPrice"] = float(exit_price_input)
    except ValueError:
        logger.error("❌ Ongeldige prijs.")

    # Resultaat
    try:
        trade["Resultaat"] = float(prompt("📉 Resultaat ($): "))
    except ValueError:
        logger.error("❌ Ongeldig bedrag.")

    # Return on Margin
    try:
        trade["ReturnOnMargin"] = float(prompt("📊 Return on Margin (%): "))
    except ValueError:
        logger.error("❌ Ongeldige waarde.")

    # Evaluatie
    print("\n🧠 Evaluatie:")
    print("Zeg iets over:")
    print(
        "- je marktinschatting (IV, richting), effectiviteit van je edge (skew, premie vs risico)"
    )
    print(
        "- je risicomanagement: wat verwachtte je, wat gebeurde er, wat concludeer je?"
    )
    print("Typ '.' op een lege regel om te stoppen:")

    lijnen = []
    while True:
        regel = prompt("> ")
        if regel.strip() == ".":
            break
        lijnen.append(regel)
    trade["Evaluatie"] = "\n".join(lijnen)

    trade["Status"] = "Gesloten"
    logger.info("✅ Trade gemarkeerd als gesloten.")


def main() -> None:
    """Interactive wrapper to close a trade from ``journal.json``."""
    setup_logging()
    logger.info("🚀 Trade afsluiten")
    journal = load_journal()
    if not journal:
        return

    print("\n📋 Open trades:")
    open_trades = [t for t in journal if t.get("Status") == "Open"]
    for t in open_trades:
        print(f"- {t['TradeID']}: {t['Symbool']} - {t['Type']}")

    keuze = prompt("\nVoer TradeID in om af te sluiten: ")
    if not is_valid_trade_id(keuze):
        logger.error("❌ Ongeldige TradeID.")
        return

    trade = next((t for t in journal if t["TradeID"] == keuze), None)
    if not trade:
        logger.error("❌ TradeID niet gevonden.")
        return

    sluit_trade_af(trade)
    update_trade(trade["TradeID"], trade)
    logger.success("✅ Trade afgesloten")


if __name__ == "__main__":
    main()
