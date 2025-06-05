"""Interactive command line interface for TOMIC utilities."""

import subprocess
import sys
from datetime import datetime
import json
from pathlib import Path
import threading

from tomic.api.market_utils import start_app
from tomic.api.base_client import BaseIBApp

from tomic import config as cfg
from tomic.logging import setup_logging
from tomic.analysis.greeks import compute_portfolio_greeks

setup_logging()

# Available log levels for loguru/logging
LOG_LEVEL_CHOICES = [
    "TRACE",
    "DEBUG",
    "INFO",
    "SUCCESS",
    "WARNING",
    "ERROR",
    "CRITICAL",
]

POSITIONS_FILE = Path(cfg.get("POSITIONS_FILE", "positions.json"))
ACCOUNT_INFO_FILE = Path(cfg.get("ACCOUNT_INFO_FILE", "account_info.json"))
META_FILE = Path(cfg.get("PORTFOLIO_META_FILE", "portfolio_meta.json"))
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


def print_saved_portfolio_greeks() -> None:
    """Compute and display portfolio Greeks from saved positions."""
    if not POSITIONS_FILE.exists():
        return
    try:
        positions = json.loads(POSITIONS_FILE.read_text())
    except Exception:
        print("⚠️ Kan portfolio niet laden voor Greeks-overzicht.")
        return
    portfolio = compute_portfolio_greeks(positions)
    print("📐 Portfolio Greeks:")
    for key, val in portfolio.items():
        print(f"{key}: {val:+.4f}")


class VersionApp(BaseIBApp):
    """Minimal IB app to retrieve the TWS server version."""

    def __init__(self) -> None:
        super().__init__()
        self.ready_event = threading.Event()

    def nextValidId(self, orderId: int) -> None:  # noqa: N802 - IB API callback
        self.ready_event.set()


def print_api_version() -> None:
    """Connect to TWS and display the server version information."""
    app = VersionApp()
    start_app(app, client_id=998)
    if app.ready_event.wait(timeout=5):
        print(f"Server versie: {app.serverVersion()}")
        print(f"Verbindingstijd: {app.twsConnectionTime()}")
    else:
        print("❌ Geen verbinding met TWS")
    app.disconnect()


def run_dataexporter() -> None:
    """Menu for export and CSV validation utilities."""
    while True:
        print("\n📤 DATA MANAGEMENT")
        print("1. Exporteer een markt (tomic.api.getonemarket)")
        print("2. Exporteer alle markten (tomic.api.getallmarkets)")
        print("3. Controleer CSV-kwaliteit (tomic.cli.csv_quality_check)")
        print("4. Haal optiedata op per symbool")
        print("5. Terug naar hoofdmenu")
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
            run_module("tomic.cli.option_lookup")
        elif sub == "5":
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
            print_saved_portfolio_greeks()
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


def run_settings_menu() -> None:
    """Menu to view and edit configuration."""
    while True:
        print("\n=== INSTELLINGEN ===")
        print("1. Toon huidige configuratie")
        print("2. Pas IB host/poort aan")
        print("3. Pas default symbols aan")
        print(f"4. Pas log-niveau aan ({', '.join(LOG_LEVEL_CHOICES)})")
        print("5. Pas interest rate aan")
        print("6. Haal TWS API-versie op")
        print("7. Terug naar hoofdmenu")
        sub = input("Maak je keuze: ").strip()

        if sub == "1":
            asdict = (
                cfg.CONFIG.model_dump
                if hasattr(cfg.CONFIG, "model_dump")
                else cfg.CONFIG.dict
            )
            for key, value in asdict().items():
                print(f"{key}: {value}")
        elif sub == "2":
            host = input(f"Host ({cfg.CONFIG.IB_HOST}): ").strip() or cfg.CONFIG.IB_HOST
            port_str = input(f"Poort ({cfg.CONFIG.IB_PORT}): ").strip()
            port = int(port_str) if port_str else cfg.CONFIG.IB_PORT
            cfg.update({"IB_HOST": host, "IB_PORT": port})
        elif sub == "3":
            print("Huidige symbols:", ", ".join(cfg.CONFIG.DEFAULT_SYMBOLS))
            raw = input("Nieuw lijst (comma-sep): ").strip()
            if raw:
                symbols = [s.strip().upper() for s in raw.split(",") if s.strip()]
                cfg.update({"DEFAULT_SYMBOLS": symbols})
        elif sub == "4":
            print("Beschikbare log-niveaus:")
            for name in LOG_LEVEL_CHOICES:
                print(f"  {name}")
            level = input(f"Log level ({cfg.CONFIG.LOG_LEVEL}): ").strip().upper()
            if level:
                if level not in LOG_LEVEL_CHOICES:
                    print("❌ Ongeldig log-niveau")
                    continue
                cfg.update({"LOG_LEVEL": level})
                setup_logging()
        elif sub == "5":
            rate_str = input(f"Rente ({cfg.CONFIG.INTEREST_RATE}): ").strip()
            if rate_str:
                try:
                    rate = float(rate_str)
                except ValueError:
                    print("❌ Ongeldige rente")
                    continue
                cfg.update({"INTEREST_RATE": rate})
        elif sub == "6":
            print_api_version()
        elif sub == "7":
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
        print("6. Instellingen")
        print("7. Stoppen")
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
            run_settings_menu()
        elif keuze == "7":
            print("Tot ziens.")
            break
        else:
            print("❌ Ongeldige keuze.")


if __name__ == "__main__":
    main()
