"""Interactive command line interface for TOMIC utilities."""

import subprocess
import sys
from datetime import datetime
import json
from pathlib import Path

from tomic.config import get as cfg_get
from tomic.logging import setup_logging

setup_logging()

POSITIONS_FILE = Path(cfg_get("POSITIONS_FILE", "positions.json"))
ACCOUNT_INFO_FILE = Path(cfg_get("ACCOUNT_INFO_FILE", "account_info.json"))
META_FILE = Path(cfg_get("PORTFOLIO_META_FILE", "portfolio_meta.json"))
STRATEGY_DASHBOARD_MODULE = "tomic.cli.strategy_dashboard"


def run_module(module_name: str, *args: str) -> None:
    """Run a Python module using ``python -m``."""
    subprocess.run([sys.executable, "-m", module_name, *args], check=True)


def save_portfolio_timestamp() -> None:
    """Store the datetime of the latest portfolio fetch."""
    META_FILE.write_text(json.dumps({"last_update": datetime.now().isoformat()}))


def load_portfolio_timestamp() -> str | None:
    """Return the ISO timestamp of the last portfolio update if available."""
    if not META_FILE.exists():
        return None
    try:
        data = json.loads(META_FILE.read_text())
        return data.get("last_update")
    except Exception:
        return None


def run_dataexporter() -> None:
    """Menu for export and CSV validation utilities."""
    while True:
        print("\n📤 DATA MANAGEMENT")
        print("1. Exporteer een markt (tomic.api.getonemarket)")
        print("2. Exporteer alle markten (tomic.api.getallmarkets)")
        print("3. Controleer CSV-kwaliteit (tomic.cli.csv_quality_check)")
        print("4. Terug naar hoofdmenu")
        sub = input("Maak je keuze: ")
        if sub == "1":
            symbol = input("Ticker symbool: ").strip()
            if not symbol:
                print("Geen symbool opgegeven")
                continue
            try:
                run_module("tomic.api.getonemarket", symbol)
            except subprocess.CalledProcessError:
                print("❌ Export mislukt")
        elif sub == "2":
            run_module("tomic.api.getallmarkets")
        elif sub == "3":
            path = input("Pad naar CSV-bestand: ").strip()
            if path:
                try:
                    run_module("tomic.cli.csv_quality_check", path)
                except subprocess.CalledProcessError:
                    print("❌ Kwaliteitscheck mislukt")
            else:
                print("Geen pad opgegeven")
        elif sub == "4":
            break
        else:
            print("❌ Ongeldige keuze")


def run_trade_management() -> None:
    """Menu for journal management tasks."""
    while True:
        print("\n=== TRADE MANAGEMENT ===")
        print("1. Overzicht bekijken")
        print("2. Nieuwe trade aanmaken")
        print("3. Trade aanpassen / snapshot toevoegen")
        print("4. Journal updaten met positie IDs")
        print("5. Trade afsluiten")
        print("6. Terug naar hoofdmenu")
        sub = input("Maak je keuze: ").strip()

        if sub == "1":
            run_module("tomic.journal.journal_inspector")
        elif sub == "2":
            run_module("tomic.journal.journal_updater")
        elif sub == "3":
            run_module("tomic.journal.journal_inspector")
        elif sub == "4":
            run_module("tomic.cli.link_positions")
        elif sub == "5":
            run_module("tomic.cli.close_trade")
        elif sub == "6":
            break
        else:
            print("❌ Ongeldige keuze")


def run_risk_tools() -> None:
    """Menu for risk analysis helpers."""
    while True:
        print("\n=== RISK TOOLS ===")
        print("1. Scenario-analyse")
        print("2. Event watcher")
        print("3. Entry checker")
        print("4. Synthetics detector")
        print("5. Cone visualizer")
        print("6. Terug naar hoofdmenu")
        sub = input("Maak je keuze: ")
        if sub == "1":
            run_module("tomic.cli.portfolio_scenario")
        elif sub == "2":
            run_module("tomic.cli.event_watcher")
        elif sub == "3":
            run_module("tomic.cli.entry_checker")
        elif sub == "4":
            run_module("tomic.cli.synthetics_detector")
        elif sub == "5":
            run_module("tomic.cli.cone_visualizer")
        elif sub == "6":
            break
        else:
            print("❌ Ongeldige keuze")


def run_portfolio_menu() -> None:
    """Menu to fetch and display portfolio information."""
    while True:
        print("\n=== PORTFOLIO OVERZICHT ===")
        print("1. Portfolio overzicht opnieuw ophalen van TWS")
        print("2. Laatst opgehaalde portfolio-overzicht tonen")
        print("3. Terug naar hoofdmenu")
        sub = input("Maak je keuze: ").strip()

        if sub == "1":
            print("ℹ️ Haal portfolio op...")
            try:
                run_module("tomic.api.getaccountinfo")
                save_portfolio_timestamp()
            except subprocess.CalledProcessError:
                print("❌ Ophalen van portfolio mislukt")
                continue
            try:
                run_module(
                    STRATEGY_DASHBOARD_MODULE,
                    str(POSITIONS_FILE),
                    str(ACCOUNT_INFO_FILE),
                )
                run_module("tomic.analysis.performance_analyzer")
            except subprocess.CalledProcessError:
                print("❌ Dashboard kon niet worden gestart")
        elif sub == "2":
            if not (POSITIONS_FILE.exists() and ACCOUNT_INFO_FILE.exists()):
                print(
                    "⚠️ Geen opgeslagen portfolio gevonden. Kies optie 1 om te verversen."
                )
                continue
            ts = load_portfolio_timestamp()
            if ts:
                print(f"ℹ️ Laatste update: {ts}")
            try:
                run_module(
                    STRATEGY_DASHBOARD_MODULE,
                    str(POSITIONS_FILE),
                    str(ACCOUNT_INFO_FILE),
                )
                run_module("tomic.analysis.performance_analyzer")
            except subprocess.CalledProcessError:
                print("❌ Dashboard kon niet worden gestart")
        elif sub == "3":
            break
        else:
            print("❌ Ongeldige keuze")


def main() -> None:
    """Start the interactive control panel."""
    while True:
        print("\n=== TOMIC CONTROL PANEL ===")
        print("1. Trading Plan")
        print("2. Portfolio-overzicht")
        print("3. Trade Management")
        print("4. Data Management")
        print("5. Risk Tools")
        print("6. Stoppen")
        keuze = input("Maak je keuze: ")

        if keuze == "1":
            run_module("tomic.cli.trading_plan")
        elif keuze == "2":
            run_portfolio_menu()
        elif keuze == "3":
            run_trade_management()
        elif keuze == "4":
            run_dataexporter()
        elif keuze == "5":
            run_risk_tools()
        elif keuze == "6":
            print("Tot ziens.")
            break
        else:
            print("❌ Ongeldige keuze.")


if __name__ == "__main__":
    main()
