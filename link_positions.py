import json
from pathlib import Path

JOURNAL_FILE = Path("journal.json")
POSITIONS_FILE = Path("positions.json")


def load_json(path):
    if not path.exists():
        print(f"⚠️ {path} niet gevonden.")
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_journal(journal):
    with open(JOURNAL_FILE, "w", encoding="utf-8") as f:
        json.dump(journal, f, indent=2)
    print("✅ Wijzigingen opgeslagen.\n")


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
        print("❌ Ongeldige keuze.")
        return None
    return int(keuze) - 1


def list_positions(symbol, positions):
    sym_pos = [p for p in positions if p.get("symbol") == symbol]
    if not sym_pos:
        print("⚠️ Geen open posities gevonden voor dit symbool.")
        return []
    print(f"\n📈 Open posities voor {symbol}:")
    for p in sym_pos:
        exp = p.get("lastTradeDate") or p.get("expiry") or p.get("expiration")
        print(f"  {symbol}, {p.get('strike')}, {exp}, {p.get('conId')}")
    return sym_pos


def main():
    journal = load_json(JOURNAL_FILE)
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
                print("✅ conId toegevoegd.")
                save_journal(journal)
            except ValueError:
                print("❌ Ongeldig conId.")


if __name__ == "__main__":
    main()
