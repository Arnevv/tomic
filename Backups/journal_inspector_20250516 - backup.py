import json
from pathlib import Path
from datetime import datetime

journal_file = Path("journal.json")

def laad_journal():
    if not journal_file.exists():
        print("⚠️ Geen journal.json gevonden.")
        return []
    with open(journal_file, "r", encoding="utf-8") as f:
        return json.load(f)

def bewaar_journal(journal):
    with open(journal_file, "w", encoding="utf-8") as f:
        json.dump(journal, f, indent=2)
    print("✅ Wijzigingen opgeslagen.\n")

def toon_overzicht(journal):
    print("\n📋 Overzicht van trades:")
    for trade in journal:
        print(f"- {trade['TradeID']}: {trade['Symbool']} - {trade['Type']} - {trade['Status']}")

def toon_details(trade):
    print(f"\n🔍 Details voor TradeID {trade['TradeID']}")
    for k, v in trade.items():
        if k == "Legs":
            print("Legs:")
            for leg in v:
                print(f"  {leg['action']} {leg['qty']}x {leg['type']} @ {leg['strike']}")
        elif k in {"Plan", "Reden", "Evaluatie"}:
            print(f"{k}:")
            if isinstance(v, str):
                for line in v.strip().splitlines():
                    print(f"  {line}")
            else:
                print(f"  {v}")
            print()
        elif k == "Greeks":
            print("Greeks:")
            for gk, gv in v.items():
                print(f"  {gk}: {gv}")
        else:
            print(f"{k}: {v}")

def pas_trade_aan(trade):
    velden = ["Plan", "Reden", "Status", "DatumUit", "Resultaat", "Opmerkingen", "Evaluatie", "ExitPrice", "ReturnOnMargin", "Greeks"]
    while True:
        print("\n📌 Kies welk veld je wilt aanpassen:")
        for i, veld in enumerate(velden, 1):
            print(f"{i}. {veld}")
        print("0. Stoppen met aanpassen")
        keuze = input("Keuze: ").strip()
        if keuze == "0":
            break
        if not keuze.isdigit() or int(keuze) not in range(1, len(velden) + 1):
            print("❌ Ongeldige keuze.")
            continue

        veld = velden[int(keuze) - 1]

        if veld in {"Plan", "Reden", "Evaluatie"}:
            print(f"\nVoer {veld} in (typ '.' op een lege regel om te stoppen):")
            lijnen = []
            while True:
                regel = input("> ")
                if regel.strip() == ".":
                    break
                lijnen.append(regel)
            if not lijnen:
                print("ℹ️ Geen wijziging.")
                continue
            trade[veld] = "\n".join(lijnen)
            print(f"✅ {veld} bijgewerkt.")
        elif veld == "Greeks":
            greeks = {}
            for greek in ["Delta", "Theta", "Gamma", "Vega"]:
                waarde = input(f"  {greek}: ").strip().replace("–", "-").replace("—", "-")
                if waarde == "":
                    greeks[greek] = None
                else:
                    try:
                        greeks[greek] = float(waarde)
                    except ValueError:
                        print(f"❌ Ongeldige waarde voor {greek}, sla deze over.")
                        greeks[greek] = None
            trade["Greeks"] = greeks
            print("✅ Greeks bijgewerkt.")
        else:
            nieuwe_waarde = input(f"Nieuwe waarde voor {veld} (leeg = annuleren): ").strip()
            if not nieuwe_waarde:
                print("ℹ️ Geen wijziging.")
                continue
            try:
                if veld in {"Resultaat", "ExitPrice", "ReturnOnMargin"}:
                    trade[veld] = float(nieuwe_waarde)
                elif veld == "Status":
                    if nieuwe_waarde not in {"Open", "Gesloten", "Gecanceld"}:
                        print("❌ Ongeldige status (gebruik: Open, Gesloten of Gecanceld).")
                        continue
                    trade[veld] = nieuwe_waarde
                elif veld == "DatumUit":
                    trade[veld] = nieuwe_waarde
                    try:
                        d_in = datetime.strptime(trade["DatumIn"], "%Y-%m-%d")
                        d_out = datetime.strptime(nieuwe_waarde, "%Y-%m-%d")
                        trade["DaysInTrade"] = (d_out - d_in).days
                        print(f"📆 DaysInTrade automatisch berekend: {trade['DaysInTrade']}")
                    except:
                        print("⚠️ Kon DaysInTrade niet berekenen (ongeldige datumnotatie?)")
                else:
                    trade[veld] = nieuwe_waarde
                print(f"✅ {veld} bijgewerkt.")
            except ValueError:
                print("❌ Ongeldige invoer.")

def main():
    journal = laad_journal()
    if not journal:
        return

    while True:
        toon_overzicht(journal)
        keuze = input("\nVoer TradeID in om details te bekijken of ENTER om terug te keren: ").strip()
        if not keuze:
            break

        trade = next((t for t in journal if t["TradeID"] == keuze), None)
        if not trade:
            print("❌ TradeID niet gevonden.")
            continue

        toon_details(trade)
        bewerk = input("\nWil je deze trade aanpassen? (j/n): ").strip().lower()
        if bewerk == "j":
            pas_trade_aan(trade)
            bewaar_journal(journal)

if __name__ == "__main__":
    main()
