from datetime import datetime
from typing import Any, Dict, Iterable

from .utils import load_journal, save_journal


def _format_leg(leg: Dict[str, Any]) -> str:
    """Return formatted leg description including optional ``conId``."""

    con_id = leg.get("conId")
    con_id_str = f" - conId: {con_id}" if con_id is not None else ""
    return (
        f"  {leg['action']} {leg['qty']}x {leg['type']} @ {leg['strike']}{con_id_str}"
    )


def toon_overzicht(journal: Iterable[Dict[str, Any]]) -> None:
    """Display a short overview of all trades."""

    print("\n📋 Overzicht van trades:")
    for trade in journal:
        print(
            f"- {trade['TradeID']}: {trade['Symbool']} - {trade['Type']} - {trade['Status']}"
        )


def print_kolomrij(label: str, key: str, trade: Dict[str, Any]) -> str:
    """Return the display value for ``key`` in ``trade``."""

    waarde = trade.get(key, "")
    return f"{label}: {waarde}"


def toon_details(trade: Dict[str, Any]) -> None:
    """Print a detailed view of a single trade."""

    print(f"\n🔍 Details voor TradeID {trade['TradeID']}")

    kolom1_keys = [
        "TradeID",
        "DatumIn",
        "DatumUit",
        "Symbool",
        "Type",
        "Expiry",
        "Spot",
    ]
    kolom2_keys = [
        "Richting",
        "Status",
        "Premium",
        "EntryPrice",
        "ExitPrice",
        "ReturnOnMargin",
        "InitMargin",
    ]
    kolom3_keys = [
        "StopPct",
        "IV_Entry",
        "HV_Entry",
        "DaysInTrade",
        "VIX",
        "ATR_14",
        "Skew",
    ]

    print("\n📄 Overzicht:")
    for r in range(max(len(kolom1_keys), len(kolom2_keys), len(kolom3_keys))):
        c1 = (
            print_kolomrij(kolom1_keys[r], kolom1_keys[r], trade)
            if r < len(kolom1_keys)
            else ""
        )
        c2 = (
            print_kolomrij(kolom2_keys[r], kolom2_keys[r], trade)
            if r < len(kolom2_keys)
            else ""
        )
        c3 = (
            print_kolomrij(kolom3_keys[r], kolom3_keys[r], trade)
            if r < len(kolom3_keys)
            else ""
        )
        print(f"  {c1:<35} {c2:<35} {c3:<35}")

    # Rest van de inhoud (legs, plan, etc.)
    for k, v in trade.items():
        if k in kolom1_keys + kolom2_keys + kolom3_keys:
            continue
        elif k == "Legs":
            print("\n📦 Legs:")
            for leg in v:
                print(_format_leg(leg))
        elif k == "Plan":
            print("\n📋 Plan:")
            for line in v.strip().splitlines():
                print(f"  {line}")
        elif k == "Reden":
            print("\n🧠 Reden:")
            for line in v.strip().splitlines():
                print(f"  {line}")
        elif k == "Exitstrategie":
            print("\n🚪 Exitstrategie:")
            for line in v.strip().splitlines():
                print(f"  {line}")
        elif k == "ExitRules":
            print("\n🚪 ExitRules:")
            for rk, rv in v.items():
                print(f"  {rk}: {rv}")
        elif k == "Opmerkingen":
            print("\n🗒️ Opmerkingen:")
            for line in v.strip().splitlines():
                print(f"  {line}")
        elif k == "Evaluatie":
            print("\n📈 Evaluatie:")
            for line in (v or "").strip().splitlines():
                print(f"  {line}")
        elif k == "Greeks":
            print("\n📐 Actuele Greeks (laatste snapshot):")
            for gk, gv in v.items():
                print(f"  {gk}: {gv}")
        elif k == "Snapshots":
            print("\n🧾 Snapshots:")
            for snap in v:
                ivr = snap.get("iv_rank")
                ivr_disp = (
                    f"{ivr * 100:.1f}" if isinstance(ivr, (int, float)) else ivr
                )
                print(
                    f"📆 {snap.get('date', '-')}: Spot {snap.get('spot')} | IV30 {snap.get('iv30')} | IV Rank {ivr_disp} | Skew {snap.get('skew')}"
                )
                g = snap.get("Greeks", {})
                print(
                    f"  Greeks → Delta: {g.get('Delta')} | Gamma: {g.get('Gamma')} | Vega: {g.get('Vega')} | Theta: {g.get('Theta')}"
                )
                note = snap.get("note", "").strip()
                if note:
                    print("  Notitie:")
                    for line in note.splitlines():
                        print(f"    {line}")


def pas_trade_aan(trade: Dict[str, Any]) -> None:
    """Interactively modify fields in ``trade``."""

    velden = [
        "Plan",
        "Reden",
        "Exitstrategie",
        "Status",
        "DatumUit",
        "Resultaat",
        "Opmerkingen",
        "Evaluatie",
        "ExitPrice",
        "ReturnOnMargin",
        "Greeks",
    ]
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
            for greek in ["Delta", "Gamma", "Vega", "Theta"]:
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
                    print(
                        f"📆 DaysInTrade automatisch berekend: {trade['DaysInTrade']}"
                    )
                except Exception:
                    print("⚠️ Kon DaysInTrade niet berekenen.")
            else:
                trade[veld] = nieuwe_waarde
            print(f"✅ {veld} bijgewerkt.")
        except ValueError:
            print("❌ Ongeldige invoer.")


def snapshot_input(trade: Dict[str, Any]) -> None:
    """Add a snapshot entry to ``trade`` with optional market data."""

    snapshot: Dict[str, Any] = {"date": datetime.now().strftime("%Y-%m-%d")}

    def float_input(prompt: str) -> float | None:
        try:
            val = input(prompt).strip()
            return float(val) if val else None
        except Exception:
            return None

    snapshot["spot"] = float_input("Spotprijs: ")
    snapshot["iv30"] = float_input("IV30: ")
    ivr_val = float_input("IV Rank: ")
    if isinstance(ivr_val, (int, float)) and ivr_val > 1:
        ivr_val /= 100
    snapshot["iv_rank"] = ivr_val
    snapshot["hv30"] = float_input("HV30: ")
    snapshot["vix"] = float_input("VIX: ")
    snapshot["atr14"] = float_input("ATR(14): ")
    iv_call = float_input("IV 25D CALL: ")
    iv_put = float_input("IV 25D PUT: ")
    snapshot["skew"] = round(iv_call - iv_put, 2) if iv_call and iv_put else None

    greeks = {}
    for greek in ["Delta", "Gamma", "Vega", "Theta"]:
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


def main() -> None:
    """Entry point for command line usage."""

    journal = load_journal()
    if not journal:
        print("\n📭 Geen trades gevonden in het journal.")
        input("Druk op ENTER om terug te keren.")
        return

    while True:
        toon_overzicht(journal)
        keuze = input(
            "\nVoer TradeID in om details te bekijken of ENTER om terug te keren: "
        ).strip()
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
                save_journal(journal)
            elif actie == "2":
                snapshot_input(trade)
                save_journal(journal)
            elif actie == "3":
                break
            else:
                print("❌ Ongeldige keuze.")


if __name__ == "__main__":
    main()
