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
        elif k == "Snapshots":
            print("\n🧾 Snapshots:")
            for snap in v:
                print(f"📆 {snap.get('date', '-')}: Spot {snap.get('spot')} | IV30 {snap.get('iv30')} | IV Rank {snap.get('iv_rank')} | Skew {snap.get('skew')}")
                g = snap.get("Greeks", {})
                print(f"  Delta: {g.get('Delta')} | Theta: {g.get('Theta')} | Gamma: {g.get('Gamma')} | Vega: {g.get('Vega')}")
                note = snap.get("note", "").strip()
                if note:
                    print("  Notitie:")
                    for line in note.splitlines():
                        print(f"    {line}")
        else:
            print(f"{k}: {v}")

def snapshot_input(trade):
    print("\n📸 Nieuwe snapshot toevoegen:")
    snapshot = {"date": datetime.now().strftime("%Y-%m-%d")}

    def float_input(prompt):
        while True:
            val = input(prompt).strip().replace("–", "-").replace("—", "-")
            if val == "":
                return None
            try:
                return float(val)
            except:
                print("❌ Ongeldige invoer. Vul een getal in zoals -4.2 of 12.8.")

    snapshot["spot"] = float_input("Spotprijs (https://marketchameleon.com/Overview/SPY/Summary): ")
    snapshot["iv30"] = float_input("IV30 (https://marketchameleon.com/Overview/SPY/Summary): ")
    snapshot["iv_rank"] = float_input("IV Rank (https://marketchameleon.com/Overview/SPY/Summary): ")
    snapshot["hv30"] = float_input("HV30 (https://www.alphaquery.com/stock/SPY/volatility-option-statistics/30-day/historical-volatility): ")
    snapshot["vix"] = float_input("VIX (https://www.barchart.com/stocks/quotes/$VIX/technical-analysis): ")
    snapshot["atr14"] = float_input("ATR(14) (https://www.barchart.com/etfs-funds/quotes/SPY/technical-analysis): ")
    print("Skew wordt berekend als: IV 25D call – IV 25D put (bijv. 12.8 – 17 = -4.2)")
    iv_call = float_input("  IV 25D CALL: ")
    iv_put = float_input("  IV 25D PUT: ")
    if iv_call is not None and iv_put is not None:
        snapshot["skew"] = round(iv_call - iv_put, 2)
    else:
        snapshot["skew"] = None

    greeks = {}
    for greek in ["Delta", "Theta", "Gamma", "Vega"]:
        greeks[greek] = float_input(f"  {greek}: ")
    snapshot["Greeks"] = greeks

    print("Notitie (typ '.' op een lege regel om te stoppen):")
    lijnen = []
    while True:
        regel = input("> ")
        if regel.strip() == ".":
            break
        lijnen.append(regel)
    snapshot["note"] = "\n".join(lijnen)

    trade.setdefault("Snapshots", []).append(snapshot)
    trade["Greeks"] = greeks
    print("✅ Snapshot toegevoegd en actuele Greeks bijgewerkt.")

def pas_trade_aan(trade):
    velden = ["Plan", "Reden", "Status", "DatumUit", "Resultaat", "Opmerkingen", "Evaluatie", "ExitPrice", "ReturnOnMargin"]
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

        while True:
            print("\nWat wil je doen?")
            print("1. Originele waarden aanpassen")
            print("2. Snapshot toevoegen")
            print("3. Terug naar overzicht")
            actie = input("Keuze: ").strip()

            if actie == "1":
                pas_trade_aan(trade)
                bewaar_journal(journal)
            elif actie == "2":
                snapshot_input(trade)
                bewaar_journal(journal)
            elif actie == "3":
                break
            else:
                print("❌ Ongeldige keuze.")

if __name__ == "__main__":
    main()
