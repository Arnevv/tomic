"""Interactive command line interface for TOMIC utilities."""

import subprocess
import sys
from datetime import datetime
import json
from pathlib import Path
import threading
import os
import csv

try:
    from tabulate import tabulate
except Exception:  # pragma: no cover - fallback when tabulate is missing

    def tabulate(
        rows: list[list[str]],
        headers: list[str] | None = None,
        tablefmt: str = "simple",
    ) -> str:
        if headers:
            table_rows = [headers] + rows
        else:
            table_rows = rows
        col_w = [max(len(str(c)) for c in col) for col in zip(*table_rows)]

        def fmt(row: list[str]) -> str:
            return (
                "| "
                + " | ".join(str(c).ljust(col_w[i]) for i, c in enumerate(row))
                + " |"
            )

        lines = []
        if headers:
            lines.append(fmt(headers))
            lines.append(
                "|-" + "-|-".join("-" * col_w[i] for i in range(len(col_w))) + "-|"
            )
        for row in rows:
            lines.append(fmt(row))
        return "\n".join(lines)


if __package__ is None:
    # Allow running this file directly without ``-m`` by adjusting ``sys.path``
    sys.path.append(str(Path(__file__).resolve().parents[1]))
    __package__ = "tomic.cli"

from .common import Menu, prompt

from tomic.api.market_utils import start_app, ib_api_available
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


def _latest_export_dir(base: Path) -> Path | None:
    """Return newest subdirectory inside ``base`` or ``None`` if none exist."""
    if not base.exists():
        return None
    subdirs = [d for d in base.iterdir() if d.is_dir()]
    if not subdirs:
        return None
    return max(subdirs, key=lambda d: d.stat().st_mtime)


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
    start_app(app)
    if app.ready_event.wait(timeout=5):
        print(f"Server versie: {app.serverVersion()}")
        print(f"Verbindingstijd: {app.twsConnectionTime()}")
    else:
        print("❌ Geen verbinding met TWS")
    app.disconnect()


def check_ib_connection() -> None:
    """Test whether the IB API is reachable."""
    if ib_api_available():
        print("✅ Verbinding met TWS beschikbaar")
    else:
        print("❌ Geen verbinding met TWS")


def run_dataexporter() -> None:
    """Menu for export and CSV validation utilities."""

    def export_one() -> None:
        symbol = prompt("Ticker symbool: ")
        if not symbol:
            print("Geen symbool opgegeven")
            return
        try:
            run_module("tomic.api.getonemarket", symbol)
        except subprocess.CalledProcessError:
            print("❌ Export mislukt")

    def export_one_prototype() -> None:
        symbol = prompt("Ticker symbool: ")
        if not symbol:
            print("Geen symbool opgegeven")
            return
        from datetime import datetime
        from tomic.proto.rpc import submit_task

        submit_task({"type": "get_market_data", "symbol": symbol.strip().upper()})
        job_id = f"{symbol.strip().upper()}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        print(f"Job {job_id} toegevoegd aan queue.")

    def csv_check() -> None:
        path = prompt("Pad naar CSV-bestand: ")
        if not path:
            print("Geen pad opgegeven")
            return
        try:
            run_module("tomic.cli.csv_quality_check", path)
        except subprocess.CalledProcessError:
            print("❌ Kwaliteitscheck mislukt")

    def export_all() -> None:
        sub = Menu("Selecteer exporttype")
        sub.add(
            "Alleen marktdata - synchroon",
            lambda: run_module("tomic.api.getallmarkets", "--only-metrics"),
        )
        sub.add(
            "Alleen marktdata - asynchroon",
            lambda: run_module("tomic.api.getallmarkets_async", "--only-metrics"),
        )
        sub.add(
            "Alleen optionchains - synchroon",
            lambda: run_module("tomic.api.getallmarkets", "--only-chains"),
        )
        sub.add(
            "Alleen optionchains - asynchroon (prototype)",
            lambda: run_module("tomic.api.getallmarkets_async", "--only-chains"),
        )
        sub.add(
            "Marktdata en optionchains",
            lambda: run_module("tomic.api.getallmarkets"),
        )
        sub.run()

    def option_lookup_default() -> None:
        os.environ["TOMIC_LOG_LEVEL"] = "DEBUG"
        try:
            run_module(
                "tomic.cli.option_lookup",
                "AAPL",
                "2025-06-20",
                "200",
                "C",
            )
        except subprocess.CalledProcessError:
            print("❌ Ophalen van optiedata mislukt")
        finally:
            os.environ["TOMIC_LOG_LEVEL"] = "INFO"

    menu = Menu("📤 DATA MANAGEMENT")
    menu.add("Exporteer een markt (tomic.api.getonemarket)", export_one)
    menu.add(
        "Exporteer een markt (via TwsSessionDaemon prototype)",
        export_one_prototype,
    )
    menu.add("Exporteer alle markten (tomic.api.getallmarkets)", export_all)
    menu.add("Controleer CSV-kwaliteit (tomic.cli.csv_quality_check)", csv_check)
    menu.add(
        "Haal optiedata op per symbool",
        option_lookup_default,
    )
    menu.run()


def run_trade_management() -> None:
    """Menu for journal management tasks."""

    menu = Menu("TRADE MANAGEMENT")
    menu.add(
        "Overzicht bekijken", lambda: run_module("tomic.journal.journal_inspector")
    )
    menu.add(
        "Nieuwe trade aanmaken", lambda: run_module("tomic.journal.journal_updater")
    )
    menu.add(
        "Trade aanpassen / snapshot toevoegen",
        lambda: run_module("tomic.journal.journal_inspector"),
    )
    menu.add(
        "Journal updaten met positie IDs",
        lambda: run_module("tomic.cli.link_positions"),
    )
    menu.add("Trade afsluiten", lambda: run_module("tomic.cli.close_trade"))
    menu.run()


def run_risk_tools() -> None:
    """Menu for risk analysis helpers."""

    menu = Menu("RISK TOOLS")
    menu.add("Scenario-analyse", lambda: run_module("tomic.cli.portfolio_scenario"))
    menu.add("Event watcher", lambda: run_module("tomic.cli.event_watcher"))
    menu.add("Entry checker", lambda: run_module("tomic.cli.entry_checker"))
    menu.add(
        "Strategievoorstellen",
        lambda: run_module("tomic.cli.generate_proposals"),
    )
    menu.add("Synthetics detector", lambda: run_module("tomic.cli.synthetics_detector"))
    menu.add("Cone visualizer", lambda: run_module("tomic.cli.cone_visualizer"))
    menu.run()


def run_portfolio_menu() -> None:
    """Menu to fetch and display portfolio information."""

    def fetch_and_show() -> None:
        print("ℹ️ Haal portfolio op...")
        try:
            run_module("tomic.api.getaccountinfo")
            save_portfolio_timestamp()
        except subprocess.CalledProcessError:
            print("❌ Ophalen van portfolio mislukt")
            return
        try:
            run_module(
                STRATEGY_DASHBOARD_MODULE,
                str(POSITIONS_FILE),
                str(ACCOUNT_INFO_FILE),
            )
            run_module("tomic.analysis.performance_analyzer")
        except subprocess.CalledProcessError:
            print("❌ Dashboard kon niet worden gestart")

    def show_saved() -> None:
        if not (POSITIONS_FILE.exists() and ACCOUNT_INFO_FILE.exists()):
            print("⚠️ Geen opgeslagen portfolio gevonden. Kies optie 1 om te verversen.")
            return
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

    def show_greeks() -> None:
        if not POSITIONS_FILE.exists():
            print("⚠️ Geen opgeslagen portfolio gevonden. Kies optie 1 om te verversen.")
            return
        try:
            run_module("tomic.cli.portfolio_greeks", str(POSITIONS_FILE))
        except subprocess.CalledProcessError:
            print("❌ Greeks-overzicht kon niet worden getoond")

    def generate_proposals_now() -> None:
        if not POSITIONS_FILE.exists():
            print("⚠️ Geen opgeslagen portfolio gevonden. Kies optie 1 om te verversen.")
            return
        base_dir = Path(cfg.get("EXPORT_DIR", "exports"))
        latest = _latest_export_dir(base_dir)
        if latest is None:
            print("⚠️ Geen exportmap gevonden")
            return
        overview = latest / "Overzicht_Marktkenmerken.csv"
        if overview.exists():
            print(f"ℹ️ Marktkenmerken uit {overview}")
            try:
                with open(overview, newline="", encoding="utf-8") as fh:
                    reader = list(csv.reader(fh))
                if reader:
                    headers, *rows = reader
                    print(tabulate(rows, headers=headers, tablefmt="github"))
            except Exception as exc:
                print(f"⚠️ Kan overzicht niet lezen: {exc}")
        else:
            print(f"⚠️ {overview.name} ontbreekt in {latest}")

        try:
            positions = json.loads(POSITIONS_FILE.read_text())
        except Exception:
            print("⚠️ Kan portfolio niet laden voor strategie-overzicht.")
            return
        totals = compute_portfolio_greeks(positions)
        delta = totals.get("Delta", 0)
        vega = totals.get("Vega", 0)
        strategies: list[str] = []
        if abs(delta) > 25:
            strategies.append("Vertical – richting kiezen (bij duidelijke bias)")
        if vega > 50:
            strategies.append("Iron Condor – vega omlaag (hoge IV, IV Rank > 30)")
        if vega < -50:
            strategies.append(
                "Calendar Spread – vega omhoog (lage IV, contango term structure)"
            )
        if strategies:
            print("\nTOMIC zoekt strategieën:")
            for s in strategies:
                print(f"- {s}")

        try:
            run_module(
                "tomic.cli.generate_proposals",
                str(POSITIONS_FILE),
                str(latest),
            )
        except subprocess.CalledProcessError:
            print("❌ Strategievoorstellen genereren mislukt")

    menu = Menu("PORTFOLIO OVERZICHT")
    menu.add("Portfolio overzicht opnieuw ophalen van TWS", fetch_and_show)
    menu.add("Laatst opgehaalde portfolio-overzicht tonen", show_saved)
    menu.add("Toon portfolio greeks", show_greeks)
    menu.add("Genereer strategieen obv portfolio greeks", generate_proposals_now)
    menu.run()


def run_settings_menu() -> None:
    """Menu to view and edit configuration."""

    def show_config() -> None:
        asdict = (
            cfg.CONFIG.model_dump
            if hasattr(cfg.CONFIG, "model_dump")
            else cfg.CONFIG.dict
        )
        for key, value in asdict().items():
            print(f"{key}: {value}")

    def change_host() -> None:
        host = prompt(f"Host ({cfg.CONFIG.IB_HOST}): ", cfg.CONFIG.IB_HOST)
        port_str = prompt(f"Poort ({cfg.CONFIG.IB_PORT}): ")
        port = int(port_str) if port_str else cfg.CONFIG.IB_PORT
        cfg.update({"IB_HOST": host, "IB_PORT": port})

    def change_symbols() -> None:
        print("Huidige symbols:", ", ".join(cfg.CONFIG.DEFAULT_SYMBOLS))
        raw = prompt("Nieuw lijst (comma-sep): ")
        if raw:
            symbols = [s.strip().upper() for s in raw.split(",") if s.strip()]
            cfg.update({"DEFAULT_SYMBOLS": symbols})

    def change_log_level() -> None:
        print("Beschikbare log-niveaus:")
        for name in LOG_LEVEL_CHOICES:
            print(f"  {name}")
        level = prompt(f"Log level ({cfg.CONFIG.LOG_LEVEL}): ").upper()
        if level and level in LOG_LEVEL_CHOICES:
            cfg.update({"LOG_LEVEL": level})
            setup_logging()
        elif level:
            print("❌ Ongeldig log-niveau")

    def change_rate() -> None:
        rate_str = prompt(f"Rente ({cfg.CONFIG.INTEREST_RATE}): ")
        if rate_str:
            try:
                rate = float(rate_str)
            except ValueError:
                print("❌ Ongeldige rente")
                return
            cfg.update({"INTEREST_RATE": rate})

    menu = Menu("INSTELLINGEN")
    menu.add("Toon huidige configuratie", show_config)
    menu.add("Pas IB host/poort aan", change_host)
    menu.add("Pas default symbols aan", change_symbols)
    menu.add(f"Pas log-niveau aan ({', '.join(LOG_LEVEL_CHOICES)})", change_log_level)
    menu.add("Pas interest rate aan", change_rate)
    menu.add("Test TWS-verbinding", check_ib_connection)
    menu.add("Haal TWS API-versie op", print_api_version)
    menu.run()


def main() -> None:
    """Start the interactive control panel."""

    menu = Menu("TOMIC CONTROL PANEL", exit_text="Stoppen")
    menu.add("Trading Plan", lambda: run_module("tomic.cli.trading_plan"))
    menu.add("Portfolio-overzicht", run_portfolio_menu)
    menu.add("Trade Management", run_trade_management)
    menu.add("Data Management", run_dataexporter)
    menu.add("Risk Tools", run_risk_tools)
    menu.add("Instellingen", run_settings_menu)
    menu.run()
    print("Tot ziens.")


if __name__ == "__main__":
    main()
