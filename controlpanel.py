import subprocess

def run_script(script_name, input_data=None):
    subprocess.run(
        ["python", script_name], check=True, text=True, input=input_data
    )

def run_dataexporter():
    markets = [
        "SPY",
        "QQQ",
        "IWM",
        "DIA",
        "VIX",
        "AAPL",
        "MSFT",
        "GOOG",
        "AMZN",
        "TSLA",
    ]
    while True:
        print("\n📤 DATAEXPORTER")
        print("1. Exporteer een specifiek symbool")
        print("2. Exporteer alle markten")
        print("3. Terug naar hoofdmenu")
        sub = input("Maak je keuze: ").strip()
        if sub == "1":
            symbol = input("Welk symbool wil je exporteren? ").strip().upper()
            if symbol:
                run_script("getonemarket.py", input_data=symbol + "\n")
            else:
                print("❌ Geen geldig symbool ingevoerd")
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
            run_script("getaccountinfo.py")
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
