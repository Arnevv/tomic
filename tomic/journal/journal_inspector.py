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

def print_kolomrij(label, key, trade):
    waarde = trade.get(key, "")
    return f"{label}: {waarde}"

def toon_details(trade):
    print(f"\n🔍 Details voor TradeID {trade['TradeID']}")

    kolom1_keys = ["TradeID", "DatumIn", "DatumUit", "Symbool", "Type", "Expiry", "Spot"]
    kolom2_keys = ["Richting", "Status", "Premium", "EntryPrice", "ExitPrice", "ReturnOnMargin", "InitMargin"]
    kolom3_keys = ["StopPct", "IV_Entry", "HV_Entry", "DaysInTrade", "VIX", "ATR_14", "Skew"]

    print("\n📄 Overzicht:")
    for r in range(max(len(kolom1_keys), len(kolom2_keys), len(kolom3_keys))):
        c1 = print_kolomrij(kolom1_keys[r], kolom1_keys[r], trade) if r < len(kolom1_keys) else ""
        c2 = print_kolomrij(kolom2_keys[r], kolom2_keys[r], trade) if r < len(kolom2_keys) else ""
        c3 = print_kolomrij(kolom3_keys[r], kolom3_keys[r], trade) if r < len(kolom3_keys) else ""
        print(f"  {c1:<35} {c2:<35} {c3:<35}")

    # Rest van de inhoud (legs, plan, etc.)
    for k, v in trade.items():
        if k in kolom1_keys + kolom2_keys + kolom3_keys:
            continue
        elif k == "Legs":
            print("\n📦 Legs:")
            for leg in v:
                print(f"  {leg['action']} {leg['qty']}x {leg['type']} @ {leg['strike']}")
        elif k == "Plan":
            print(f"\n📋 Plan:")
            for line in v.strip().splitlines():
                print(f"  {line}")
        elif k == "Reden":
            print(f"\n🧠 Reden:")
            for line in v.strip().splitlines():
                print(f"  {line}")
        elif k == "Exitstrategie":
            print(f"\n🚪 Exitstrategie:")
            for line in v.strip().splitlines():
                print(f"  {line}")
        elif k == "Opmerkingen":
            print(f"\n🗒️ Opmerkingen:")
            for line in v.strip().splitlines():
                print(f"  {line}")
        elif k == "Evaluatie":
            print(f"\n📈 Evaluatie:")
            for line in (v or "").strip().splitlines():
                print(f"  {line}")
        elif k == "Greeks":
            print("\n📐 Actuele Greeks (laatste snapshot):")
            for gk, gv in v.items():
                print(f"  {gk}: {gv}")
        elif k == "Snapshots":
            print("\n🧾 Snapshots:")
            for snap in v:
                print(f"📆 {snap.get('date', '-')}: Spot {snap.get('spot')} | IV30 {snap.get('iv30')} | IV Rank {snap.get('iv_rank')} | Skew {snap.get('skew')}")
                g = snap.get("Greeks", {})
                print(f"  Greeks → Delta: {g.get('Delta')} | Theta: {g.get('Theta')} | Gamma: {g.get('Gamma')} | Vega: {g.get('Vega')}")
                note = snap.get("note", "").strip()
                if note:
                    print("  Notitie:")
                    for line in note.splitlines():
                        print(f"    {line}")

def pas_trade_aan(trade):
    velden = ["Plan", "Reden", "Exitstrategie", "Status", "DatumUit", "Resultaat", "Opmerkingen", "Evaluatie", "ExitPrice", "ReturnOnMargin", "Greeks"]
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

        if veld == "Greeks":
            greeks = {}
            for greek in ["Delta", "Theta", "Gamma", "Vega"]:
                waarde = input(f"  {greek}: ").strip()
                greeks[greek] = float(waarde) if waarde else None
            trade["Greeks"] = greeks
            print("✅ Greeks bijgewerkt.")
            continue

        nieuwe_waarde = input(f"Nieuwe waarde voor {veld} (leeg = annuleren): ").strip()
        if not nieuwe_waarde:
            print("ℹ️ Geen wijziging.")
            continue
        try:
            if veld in {"Resultaat", "ExitPrice", "ReturnOnMargin"}:
                trade[veld] = float(nieuwe_waarde)
            elif veld == "Status":
                if nieuwe_waarde not in {"Open", "Gesloten", "Gecanceld"}:
                    print("❌ Ongeldige status.")
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
                    print("⚠️ Kon DaysInTrade niet berekenen.")
            else:
                trade[veld] = nieuwe_waarde
            print(f"✅ {veld} bijgewerkt.")
        except ValueError:
            print("❌ Ongeldige invoer.")

def snapshot_input(trade):
    snapshot = {"date": datetime.now().strftime("%Y-%m-%d")}
    def float_input(prompt):
        try:
            val = input(prompt).strip()
            return float(val) if val else None
        except:
            return None

    snapshot["spot"] = float_input("Spotprijs: ")
    snapshot["iv30"] = float_input("IV30: ")
    snapshot["iv_rank"] = float_input("IV Rank: ")
    snapshot["hv30"] = float_input("HV30: ")
    snapshot["vix"] = float_input("VIX: ")
    snapshot["atr14"] = float_input("ATR(14): ")
    iv_call = float_input("IV 25D CALL: ")
    iv_put = float_input("IV 25D PUT: ")
    snapshot["skew"] = round(iv_call - iv_put, 2) if iv_call and iv_put else None

    greeks = {}
    for greek in ["Delta", "Theta", "Gamma", "Vega"]:
        greeks[greek] = float_input(f"{greek}: ")
    snapshot["Greeks"] = greeks

    print("Notitie (typ '.' op lege regel om te stoppen):")
    lijnen = []
    while True:
        regel = input("> ")
        if regel.strip() == ".":
            break
        lijnen.append(regel)
    snapshot["note"] = "\n".join(lijnen)

    trade.setdefault("Snapshots", []).append(snapshot)
    trade["Greeks"] = greeks
    print("✅ Snapshot toegevoegd.")

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
