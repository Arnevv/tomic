import subprocess
import os


def run_script(script_name, *args):
    """Run a Python script with optional arguments."""
    subprocess.run(["python", script_name, *args], check=True)

def run_dataexporter():
    while True:
        print("\n📤 DATAEXPORTER")
        print("1. Exporteer een markt (getonemarket.py)")
        print("2. Exporteer alle markten (getallmarkets.py)")
        print("3. Terug naar hoofdmenu")
        sub = input("Maak je keuze: ")
        if sub == "1":
            run_script("getonemarket.py")
        elif sub == "2":
            run_script("getallmarkets.py")
        elif sub == "3":
            break
        else:
            print("❌ Ongeldige keuze")

def run_trade_management():
    while True:
        print("\n=== TRADE MANAGEMENT ===")
        print("a. Overzicht bekijken")
        print("b. Nieuwe trade aanmaken")
        print("c. Trade aanpassen / snapshot toevoegen")
        print("d. Trade afsluiten")
        print("e. Terug naar hoofdmenu")
        sub = input("Maak je keuze: ").strip().lower()

        if sub == "a":
            run_script("journal_inspector.py")
        elif sub == "b":
            run_script("journal_updater.py")
        elif sub == "c":
            run_script("journal_inspector.py")
        elif sub == "d":
            run_script("close_trade.py")
        elif sub == "e":
            break
        else:
            print("❌ Ongeldige keuze")

def main():
    while True:
        print("\n=== TOMIC CONTROL PANEL ===")
        print("1. Portfolio-overzicht")
        print("2. Trade Management")
        print("3. Dataexporter (option chain / marktdata)")
        print("4. Stoppen")
        keuze = input("Maak je keuze: ")

        if keuze == "1":
            # Toon dashboard op basis van laatst opgeslagen posities
            if not os.path.exists("positions.json"):
                print("\u2139\ufe0f Positiebestand ontbreekt, haal portfolio op...")
                try:
                    run_script("getaccountinfo.py")
                except subprocess.CalledProcessError:
                    print("❌ Ophalen van portfolio mislukt")
                    continue
            try:
                run_script("strategy_dashboard.py", "positions.json")
            except subprocess.CalledProcessError:
                print("❌ Dashboard kon niet worden gestart")
        elif keuze == "2":
            run_trade_management()
        elif keuze == "3":
            run_dataexporter()
        elif keuze == "4":
            print("Tot ziens.")
            break
        else:
            print("❌ Ongeldige keuze.")

if __name__ == "__main__":
    main()
