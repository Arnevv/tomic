import subprocess

def run_script(script_name):
    subprocess.run(["python", script_name], check=True)

def run_dataexporter():
    while True:
        print("\n📤 DATAEXPORTER")
        print("1. Export optiechain (getfulloptionchain.py)")
        print("2. Export algemene data (getdata.py)")
        print("3. Terug naar hoofdmenu")
        sub = input("Maak je keuze: ")
        if sub == "1":
            run_script("getfulloptionchain_20250517.py")
        elif sub == "2":
            run_script("getdata_20250517.py")
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
            run_script("journal_inspector_20250517.py")
        elif sub == "b":
            run_script("journal_updater_20250517.py")
        elif sub == "c":
            run_script("journal_inspector_20250517.py")
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
            run_script("getaccountinfo_20250517.py")
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
