import json
from datetime import date
from pathlib import Path

# Bestandspad
journal_file = Path("journal.json")

# Zorg dat het journalbestand bestaat
if not journal_file.exists():
    with open(journal_file, "w", encoding="utf-8") as f:
        json.dump([], f)

def interactieve_trade_invoer():
    print("\n🆕 Nieuwe Trade Invoeren (meerdere legs ondersteund)\nLaat een veld leeg om af te breken.\n")

    trade_id = input("TradeID (bijv. T20240513A): ").strip()
    if not trade_id:
        return

    symbool = input("Symbool (bijv. SPY): ").strip()
    trade_type = input("Strategie type (bijv. Put Ratio Spread): ").strip()
    expiry = input("Expiry (YYYY-MM-DD): ").strip()
    richting = input("Richting (Bullish / Bearish / Sideways): ").strip()

    # Legs invoer
    legs = []
    print("\nVoer legs in. Typ ENTER bij strike om te stoppen.")
    while True:
        strike_input = input("  Strike: ").strip()
        if not strike_input:
            break
        try:
            strike = float(strike_input)
        except ValueError:
            print("❌ Ongeldige strike.")
            continue

        right = input("  Type (CALL of PUT): ").strip().upper()
        if right not in {"CALL", "PUT"}:
            print("❌ Alleen CALL of PUT toegestaan.")
            continue

        action = input("  Actie (BUY of SELL): ").strip().upper()
        if action not in {"BUY", "SELL"}:
            print("❌ Alleen BUY of SELL toegestaan.")
            continue

        qty_input = input("  Aantal contracts: ").strip()
        try:
            qty = int(qty_input)
        except ValueError:
            print("❌ Ongeldig aantal.")
            continue

        legs.append({
            "strike": strike,
            "type": right,
            "action": action,
            "qty": qty
        })

    if not legs:
        print("❌ Geen geldige legs ingevoerd.")
        return

    premium_input = input("\nNetto ontvangen/ingezette premium (bijv. 1.10): ").strip()
    try:
        premium = float(premium_input)
    except ValueError:
        print("❌ Ongeldige premium.")
        return

    while True:
        stop_pct_input = input("Stop-loss % (bijv. 20): ").strip()
        try:
            stop_pct = int(stop_pct_input)
            break
        except ValueError:
            print("❌ Ongeldige invoer. Vul een getal in.")

    print("\nVoer plan in (typ '.' op een lege regel om te stoppen):")
    lijnen = []
    while True:
        regel = input("> ")
        if regel.strip() == ".":
            break
        lijnen.append(regel)
    plan = "\n".join(lijnen)

    print("\nVoer reden in (typ '.' op een lege regel om te stoppen):")
    lijnen = []
    while True:
        regel = input("> ")
        if regel.strip() == ".":
            break
        lijnen.append(regel)
    reden = "\n".join(lijnen)

    nieuwe_trade = {
        "TradeID": trade_id,
        "DatumIn": str(date.today()),
        "DatumUit": None,
        "Symbool": symbool,
        "Type": trade_type,
        "Expiry": expiry,
        "Richting": richting,
        "Status": "Open",
        "Premium": premium,
        "EntryPrice": premium,
        "ExitPrice": None,
        "ReturnOnMargin": None,
        "StopPct": stop_pct,
        "IV_Entry": None,
        "HV_Entry": None,
        "DaysInTrade": None,
        "Plan": plan,
        "Reden": reden,
        "Evaluatie": None,
        "Resultaat": None,
        "Opmerkingen": "",
        "Legs": legs,
        "AdjustmentHistory": [],
        "Greeks": {
            "Delta": None,
            "Theta": None,
            "Gamma": None,
            "Vega": None
        }
    }

    # Voeg toe aan journal
    with open(journal_file, "r", encoding="utf-8") as f:
        journal = json.load(f)

    journal.append(nieuwe_trade)

    with open(journal_file, "w", encoding="utf-8") as f:
        json.dump(journal, f, indent=2)

    print(f"\n✅ Trade {trade_id} succesvol toegevoegd aan journal.json")

if __name__ == "__main__":
    interactieve_trade_invoer()
