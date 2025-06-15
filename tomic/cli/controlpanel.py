"""Interactive command line interface for TOMIC utilities."""

import subprocess
import sys
from datetime import datetime
import json
from pathlib import Path
import os
import csv
import tempfile

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

from tomic.cli.common import Menu, prompt

from tomic.api.ib_connection import connect_ib

from tomic import config as cfg
from tomic.logutils import setup_logging
from tomic.analysis.greeks import compute_portfolio_greeks
from tomic.analysis.vol_db import init_db, load_latest_stats

setup_logging()
try:
    cfg.update({"VOLATILITY_DB": "data/volatility.db"})
except RuntimeError:
    # Optional PyYAML dependency not available during some unit tests
    pass

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


def print_api_version() -> None:
    """Connect to TWS and display the server version information."""
    try:
        app = connect_ib()
        print(f"Server versie: {app.serverVersion()}")
        print(f"Verbindingstijd: {app.twsConnectionTime()}")
    except Exception:
        print("❌ Geen verbinding met TWS")
        return
    finally:
        try:
            app.disconnect()
        except Exception:
            pass


def check_ib_connection() -> None:
    """Test whether the IB API is reachable."""
    try:
        app = connect_ib()
        app.disconnect()
        print("✅ Verbinding met TWS beschikbaar")
    except Exception:
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
            "Alleen marktdata",
            lambda: run_module("tomic.api.getallmarkets_async", "--only-metrics"),
        )
        sub.add(
            "Alleen optionchains",
            lambda: run_module("tomic.api.getallmarkets_async", "--only-chains"),
        )
        sub.add(
            "Marktdata en optionchains",
            lambda: run_module("tomic.api.getallmarkets_async"),
        )
        sub.run()

    def bench_getonemarket() -> None:
        raw = prompt("Symbolen (spatiegescheiden): ")
        symbols = [s.strip().upper() for s in raw.split() if s.strip()]
        if not symbols:
            print("Geen symbolen opgegeven")
            return
        try:
            run_module("tomic.analysis.bench_getonemarket", *symbols)
        except subprocess.CalledProcessError:
            print("❌ Benchmark mislukt")


    def fetch_prices() -> None:
        raw = prompt("Symbolen (spatiegescheiden, leeg=default): ")
        symbols = [s.strip().upper() for s in raw.split() if s.strip()]
        try:
            run_module("tomic.cli.fetch_prices", *symbols)
        except subprocess.CalledProcessError:
            print("❌ Ophalen van prijzen mislukt")

    def show_history() -> None:
        symbol = prompt("Ticker symbool: ")
        if not symbol:
            print("Geen symbool opgegeven")
            return
        conn = init_db(cfg.get("VOLATILITY_DB", "data/volatility.db"))
        try:
            cur = conn.execute(
                "SELECT date, close FROM PriceHistory WHERE symbol=? ORDER BY date DESC LIMIT 10",
                (symbol.upper(),),
            )
            rows = cur.fetchall()
        finally:
            conn.close()
        if not rows:
            print("⚠️ Geen data gevonden")
            return
        print(tabulate(rows, headers=["Datum", "Close"], tablefmt="github"))

    def show_volstats() -> None:
        try:
            run_module("tomic.cli.show_volstats")
        except subprocess.CalledProcessError:
            print("❌ Tonen van volatiliteitsdata mislukt")

    menu = Menu("📁 DATA & MARKTDATA")
    menu.add("Exporteer een markt", export_one)
    menu.add("Exporteer alle markten", export_all)
    menu.add("Controleer CSV-kwaliteit", csv_check)
    menu.add("Benchmark getonemarket", bench_getonemarket)
    menu.add("Ophalen historische prijzen", fetch_prices)
    menu.add("Toon historische data", show_history)
    menu.add("Toon volatiliteitsdata", show_volstats)

    menu.run()

def run_trade_management() -> None:
    """Menu for journal management tasks."""

    menu = Menu("⚙️ TRADES & JOURNAL")
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

    menu = Menu("🚦 RISICO TOOLS & SYNTHETICA")
    menu.add("Entry checker", lambda: run_module("tomic.cli.entry_checker"))
    menu.add("Scenario-analyse", lambda: run_module("tomic.cli.portfolio_scenario"))
    menu.add("Event watcher", lambda: run_module("tomic.cli.event_watcher"))
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
        try:
            positions = json.loads(POSITIONS_FILE.read_text())
        except Exception:
            print("⚠️ Kan portfolio niet laden voor strategie-overzicht.")
            return
        overview = latest / "Overzicht_Marktkenmerken.csv"
        metrics: dict[str, dict] = {}
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
            symbols = {p.get("symbol") for p in positions if p.get("symbol")}
            conn = init_db(cfg.get("VOLATILITY_DB", "data/volatility.db"))
            try:
                stats = load_latest_stats(conn, symbols)
            finally:
                conn.close()
            if stats:
                headers = [
                    "Symbol",
                    "Date",
                    "IV",
                    "HV30",
                    "HV60",
                    "HV90",
                    "Rank",
                    "Pct",
                ]
                rows = [
                    [
                        r.symbol,
                        r.date,
                        r.iv,
                        r.hv30,
                        r.hv60,
                        r.hv90,
                        r.iv_rank,
                        r.iv_percentile,
                    ]
                    for r in stats.values()
                ]
                print(tabulate(rows, headers=headers, tablefmt="github"))
                metrics = {sym: rec.__dict__ for sym, rec in stats.items()}
            else:
                print("⚠️ Geen volatiliteitsdata in database")

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
            if metrics:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as fh:
                    fh.write(json.dumps(metrics).encode())
                    metrics_path = fh.name
                run_module(
                    "tomic.cli.generate_proposals",
                    str(POSITIONS_FILE),
                    str(latest),
                    metrics_path,
                )
                os.unlink(metrics_path)
            else:
                run_module(
                    "tomic.cli.generate_proposals",
                    str(POSITIONS_FILE),
                    str(latest),
                )
        except subprocess.CalledProcessError:
            print("❌ Strategievoorstellen genereren mislukt")

    menu = Menu("📊 ANALYSE & STRATEGIE")
    menu.add("Trading Plan", lambda: run_module("tomic.cli.trading_plan"))
    menu.add("Portfolio ophalen en tonen", fetch_and_show)
    menu.add("Laatst opgehaalde portfolio tonen", show_saved)
    menu.add("Toon portfolio greeks", show_greeks)
    menu.add("Strategie voorstellen", generate_proposals_now)
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
        sub = Menu("Kies log-niveau")

        def set_info() -> None:
            cfg.update({"LOG_LEVEL": "INFO"})
            os.environ["TOMIC_LOG_LEVEL"] = "INFO"
            setup_logging()

        def set_debug() -> None:
            cfg.update({"LOG_LEVEL": "DEBUG"})
            os.environ["TOMIC_LOG_LEVEL"] = "DEBUG"
            setup_logging()

        sub.add("info", set_info)
        sub.add("debug", set_debug)
        sub.run()

    def change_rate() -> None:
        rate_str = prompt(f"Rente ({cfg.CONFIG.INTEREST_RATE}): ")
        if rate_str:
            try:
                rate = float(rate_str)
            except ValueError:
                print("❌ Ongeldige rente")
                return
            cfg.update({"INTEREST_RATE": rate})

    def change_path(key: str) -> None:
        current = getattr(cfg.CONFIG, key)
        value = prompt(f"{key} ({current}): ")
        if value:
            cfg.update({key: value})

    def change_int(key: str) -> None:
        current = getattr(cfg.CONFIG, key)
        val = prompt(f"{key} ({current}): ")
        if val:
            try:
                cfg.update({key: int(val)})
            except ValueError:
                print("❌ Ongeldige waarde")

    def change_float(key: str) -> None:
        current = getattr(cfg.CONFIG, key)
        val = prompt(f"{key} ({current}): ")
        if val:
            try:
                cfg.update({key: float(val)})
            except ValueError:
                print("❌ Ongeldige waarde")

    def change_str(key: str) -> None:
        current = getattr(cfg.CONFIG, key)
        val = prompt(f"{key} ({current}): ", current)
        if val:
            cfg.update({key: val})

    def run_connection_menu() -> None:
        sub = Menu("Verbinding")
        sub.add("Pas IB host/poort aan", change_host)
        sub.add("Test TWS-verbinding", check_ib_connection)
        sub.add("Haal TWS API-versie op", print_api_version)
        sub.run()

    def run_general_menu() -> None:
        sub = Menu("Algemeen")
        sub.add("Pas default symbols aan", change_symbols)
        sub.add("Pas log-niveau aan (INFO/DEBUG)", change_log_level)
        sub.add("Pas interest rate aan", change_rate)
        sub.run()

    def run_paths_menu() -> None:
        sub = Menu("Bestanden")
        sub.add("ACCOUNT_INFO_FILE", lambda: change_path("ACCOUNT_INFO_FILE"))
        sub.add("JOURNAL_FILE", lambda: change_path("JOURNAL_FILE"))
        sub.add("POSITIONS_FILE", lambda: change_path("POSITIONS_FILE"))
        sub.add("PORTFOLIO_META_FILE", lambda: change_path("PORTFOLIO_META_FILE"))
        sub.add("VOLATILITY_DATA_FILE", lambda: change_path("VOLATILITY_DATA_FILE"))
        sub.add("VOLATILITY_DB", lambda: change_path("VOLATILITY_DB"))
        sub.add("EXPORT_DIR", lambda: change_path("EXPORT_DIR"))
        sub.run()

    def run_network_menu() -> None:
        sub = Menu("Netwerk")
        sub.add(
            "CONTRACT_DETAILS_TIMEOUT",
            lambda: change_int("CONTRACT_DETAILS_TIMEOUT"),
        )
        sub.add(
            "CONTRACT_DETAILS_RETRIES",
            lambda: change_int("CONTRACT_DETAILS_RETRIES"),
        )
        sub.add("DOWNLOAD_TIMEOUT", lambda: change_int("DOWNLOAD_TIMEOUT"))
        sub.add("DOWNLOAD_RETRIES", lambda: change_int("DOWNLOAD_RETRIES"))
        sub.add(
            "MAX_CONCURRENT_REQUESTS",
            lambda: change_int("MAX_CONCURRENT_REQUESTS"),
        )
        sub.run()

    def run_option_menu() -> None:
        sub = Menu("Optie parameters")
        sub.add("PRIMARY_EXCHANGE", lambda: change_str("PRIMARY_EXCHANGE"))
        sub.add("STRIKE_RANGE", lambda: change_int("STRIKE_RANGE"))
        sub.add("DELTA_MIN", lambda: change_float("DELTA_MIN"))
        sub.add("AMOUNT_REGULARS", lambda: change_int("AMOUNT_REGULARS"))
        sub.add("AMOUNT_WEEKLIES", lambda: change_int("AMOUNT_WEEKLIES"))
        sub.run()

    menu = Menu("🔧 CONFIGURATIE")
    menu.add("Toon huidige configuratie", show_config)
    menu.add("Verbinding", run_connection_menu)
    menu.add("Algemene opties", run_general_menu)
    menu.add("Bestanden", run_paths_menu)
    menu.add("Netwerk", run_network_menu)
    menu.add("Optie parameters", run_option_menu)
    menu.run()


def main() -> None:
    """Start the interactive control panel."""

    menu = Menu("TOMIC CONTROL PANEL", exit_text="Stoppen")
    menu.add("Analyse & Strategie", run_portfolio_menu)
    menu.add("Data & Marktdata", run_dataexporter)
    menu.add("Trades & Journal", run_trade_management)
    menu.add("Risicotools & Synthetica", run_risk_tools)
    menu.add("Configuratie", run_settings_menu)
    menu.run()
    print("Tot ziens.")


if __name__ == "__main__":
    main()
