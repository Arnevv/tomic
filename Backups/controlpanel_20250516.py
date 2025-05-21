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
            run_script("getfulloptionchain.py")
        elif sub == "2":
            run_script("getdata.py")
        elif sub == "3":
            break
        else:
            print("❌ Ongeldige keuze")

def main():
    while True:
        print("\n=== TOMIC CONTROL PANEL ===")
        print("1. Portfolio-overzicht (getaccountinfo_20250517.py)")
        print("2. Trade Journal Overzicht (journal_inspector.py)")
        print("3. Nieuwe Trade Loggen (journal_updater.py)")
        print("4. Dataexporter (option chain / marktdata)")
        print("5. Stoppen")
        keuze = input("Maak je keuze: ")

        if keuze == "1":
            run_script("getaccountinfo_20250517.py")
        elif keuze == "2":
            run_script("journal_inspector_20250517.py")
        elif keuze == "3":
            run_script("journal_updater_20250517.py")
        elif keuze == "4":
            run_dataexporter()
        elif keuze == "5":
            print("Tot ziens.")
            break
        else:
            print("❌ Ongeldige keuze.")

if __name__ == "__main__":
    main()