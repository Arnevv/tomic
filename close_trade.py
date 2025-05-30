import logging
from datetime import datetime

from tomic.logging import setup_logging
from tomic.journal.utils import load_journal, save_journal

def sluit_trade_af(trade):
    logging.info("\n🔚 Trade afsluiten: %s - %s - %s", trade['TradeID'], trade['Symbool'], trade['Type'])

    # DatumUit en DaysInTrade
    datum_uit = input("📆 DatumUit (YYYY-MM-DD): ").strip()
    try:
        d_in = datetime.strptime(trade["DatumIn"], "%Y-%m-%d")
        d_out = datetime.strptime(datum_uit, "%Y-%m-%d")
        trade["DatumUit"] = datum_uit
        trade["DaysInTrade"] = (d_out - d_in).days
        logging.info("📅 DaysInTrade berekend: %s dagen", trade['DaysInTrade'])
    except Exception:
        logging.error("⚠️ Ongeldige datum. Sla DaysInTrade over.")
        trade["DatumUit"] = datum_uit

    # ExitPrice met EntryPrice ter referentie
    try:
        entry_price = trade.get("EntryPrice", "?")
        exit_price_input = input(f"💰 Exitprijs (de entry prijs was: {entry_price}): ").strip()
        trade["ExitPrice"] = float(exit_price_input)
    except ValueError:
        logging.error("❌ Ongeldige prijs.")

    # Resultaat
    try:
        trade["Resultaat"] = float(input("📉 Resultaat ($): ").strip())
    except ValueError:
        logging.error("❌ Ongeldig bedrag.")

    # Return on Margin
    try:
        trade["ReturnOnMargin"] = float(input("📊 Return on Margin (%): ").strip())
    except ValueError:
        logging.error("❌ Ongeldige waarde.")

    # Evaluatie
    print("\n🧠 Evaluatie:")
    print("Zeg iets over:")
    print("- je marktinschatting (IV, richting), effectiviteit van je edge (skew, premie vs risico)")
    print("- je risicomanagement: wat verwachtte je, wat gebeurde er, wat concludeer je?")
    print("Typ '.' op een lege regel om te stoppen:")

    lijnen = []
    while True:
        regel = input("> ")
        if regel.strip() == ".":
            break
        lijnen.append(regel)
    trade["Evaluatie"] = "\n".join(lijnen)

    trade["Status"] = "Gesloten"
    logging.info("✅ Trade gemarkeerd als gesloten.")

def main():
    setup_logging()
    journal = load_journal()
    if not journal:
        return

    print("\n📋 Open trades:")
    open_trades = [t for t in journal if t.get("Status") == "Open"]
    for t in open_trades:
        print(f"- {t['TradeID']}: {t['Symbool']} - {t['Type']}")

    keuze = input("\nVoer TradeID in om af te sluiten: ").strip()
    trade = next((t for t in journal if t["TradeID"] == keuze), None)
    if not trade:
        logging.error("❌ TradeID niet gevonden.")
        return

    sluit_trade_af(trade)
    save_journal(journal)

if __name__ == "__main__":
    main()
