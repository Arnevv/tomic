import json
import logging
from pathlib import Path

from tomic.config import get as cfg_get
from tomic.logging import setup_logging
from tomic.journal.utils import load_journal, save_journal

JOURNAL_FILE = Path(cfg_get("JOURNAL_FILE", "journal.json"))
POSITIONS_FILE = Path(cfg_get("POSITIONS_FILE", "positions.json"))


def load_json(path):
    if not path.exists():
        logging.error("⚠️ %s niet gevonden.", path)
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)




def list_open_trades(journal):
    open_trades = [t for t in journal if t.get("Status") == "Open"]
    print("\n📋 Open trades:")
    for t in open_trades:
        print(f"- {t['TradeID']}: {t['Symbool']} - {t['Type']}")
    return open_trades


def choose_trade(open_trades):
    keuze = input("\nVoer TradeID in (ENTER om te stoppen): ").strip()
    if not keuze:
        return None
    return next((t for t in open_trades if t["TradeID"] == keuze), None)


def choose_leg(trade):
    print("\n📦 Legs:")
    legs = trade.get("Legs", [])
    for i, leg in enumerate(legs, 1):
        print(f"{i}. {leg['action']} {leg['qty']}x {leg['type']} @ {leg['strike']}")
    keuze = input("Kies leg nummer om conId toe te voegen (ENTER voor terug): ").strip()
    if not keuze:
        return None
    if not keuze.isdigit() or int(keuze) not in range(1, len(legs) + 1):
        logging.error("❌ Ongeldige keuze.")
        return None
    return int(keuze) - 1


def list_positions(symbol, positions):
    sym_pos = [p for p in positions if p.get("symbol") == symbol]
    if not sym_pos:
        logging.error("⚠️ Geen open posities gevonden voor dit symbool.")
        return []
    print(f"\n📈 Open posities voor {symbol}:")
    for p in sym_pos:
        exp = p.get("lastTradeDate") or p.get("expiry") or p.get("expiration")
        qty = p.get("position")
        qty_disp = int(qty) if qty is not None else "?"
        right = p.get("right")
        if right == "C":
            right_disp = "Call"
        elif right == "P":
            right_disp = "Put"
        else:
            right_disp = right or ""
        print(
            f"  {symbol}, {p.get('strike')} {right_disp}, {exp}, {qty_disp}, {p.get('conId')}"
        )
    return sym_pos


def main():
    setup_logging()
    journal = load_journal(JOURNAL_FILE)
    positions = load_json(POSITIONS_FILE)
    if not journal:
        return

    while True:
        open_trades = list_open_trades(journal)
        trade = choose_trade(open_trades)
        if not trade:
            break

        while True:
            list_positions(trade.get("Symbool"), positions)
            idx = choose_leg(trade)
            if idx is None:
                break
            conid_input = input("Voer conId in (ENTER om te annuleren): ").strip()
            if not conid_input:
                continue
            try:
                trade["Legs"][idx]["conId"] = int(conid_input)
                logging.info("✅ conId toegevoegd.")
                save_journal(journal)
                logging.info("✅ Wijzigingen opgeslagen.")
            except ValueError:
                logging.error("❌ Ongeldig conId.")


if __name__ == "__main__":
    main()
