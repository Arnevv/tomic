"""Interactive command line interface for TOMIC utilities."""

import subprocess
import sys
from datetime import datetime
import json
from pathlib import Path
import os

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

from tomic.cli.common import Menu, prompt, prompt_yes_no

from tomic.api.ib_connection import connect_ib

from tomic import config as cfg
from tomic.logutils import setup_logging
from tomic.analysis.greeks import compute_portfolio_greeks
from tomic.journal.utils import load_json
from tomic.utils import today

setup_logging()


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

    def export_chain_bulk() -> None:
        symbol = prompt("Ticker symbool: ")
        if not symbol:
            print("Geen symbool opgegeven")
            return
        try:
            run_module("tomic.cli.option_lookup_bulk", symbol)
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
        base = Path(cfg.get("PRICE_HISTORY_DIR", "tomic/data/spot_prices"))
        data = load_json(base / f"{symbol.upper()}.json")
        rows = [[rec.get("date"), rec.get("close")] for rec in data[-10:]] if isinstance(data, list) else []
        if not rows:
            print("⚠️ Geen data gevonden")
            return
        rows.sort(key=lambda r: r[0], reverse=True)
        print(tabulate(rows, headers=["Datum", "Close"], tablefmt="github"))


    def polygon_chain() -> None:
        symbol = prompt("Ticker symbool: ")
        if not symbol:
            print("Geen symbool opgegeven")
            return
        from tomic.polygon_client import PolygonClient

        client = PolygonClient()
        client.connect()
        try:
            data = client.fetch_option_chain(symbol)
            print(f"Ontvangen {len(data)} contracten")
        except Exception:
            print("❌ Ophalen van optionchain mislukt")
        finally:
            client.disconnect()

    def polygon_metrics() -> None:
        symbol = prompt("Ticker symbool: ")
        if not symbol:
            print("Geen symbool opgegeven")
            return
        from tomic.polygon_client import PolygonClient

        client = PolygonClient()
        client.connect()
        try:
            metrics = client.fetch_market_metrics(symbol)
            print(json.dumps(metrics, indent=2))
        except Exception:
            print("❌ Ophalen van metrics mislukt")
        finally:
            client.disconnect()

    def process_flatfiles_default() -> None:
        symbols = [s.upper() for s in cfg.get("DEFAULT_SYMBOLS", [])]
        if not symbols:
            print("⚠️ Geen default symbolen gevonden")
            return
        print("🚀 Verwerk flatfiles voor:", " ".join(symbols))
        try:
            run_module("tomic.cli.import_flatfiles", "--keep", *symbols)
        except subprocess.CalledProcessError:
            print("❌ Flatfile verwerking mislukt")

    def process_flatfiles_specific() -> None:
        raw = prompt("Symbolen (gescheiden door komma's): ")
        symbols = [s.strip().upper() for s in raw.split(',') if s.strip()]
        if not symbols:
            print("Geen symbolen opgegeven")
            return
        print("🚀 Verwerk flatfiles voor:", " ".join(symbols))
        try:
            run_module("tomic.cli.import_flatfiles", "--keep", *symbols)
        except subprocess.CalledProcessError:
            print("❌ Flatfile verwerking mislukt")

    def process_flatfiles_menu() -> None:
        sub = Menu("Verwerk Flatfile")
        sub.add(
            "Verwerk alle default markten uit config",
            process_flatfiles_default,
        )
        sub.add(
            "Verwerk specifieke symbolen (gescheiden door komma’s)",
            process_flatfiles_specific,
        )
        sub.run()

    menu = Menu("📁 DATA & MARKTDATA")
    menu.add("Exporteer een markt", export_one)
    menu.add("OptionChain Export (BulkQualifyFlow)", export_chain_bulk)
    menu.add("Exporteer alle markten", export_all)
    menu.add("Controleer CSV-kwaliteit", csv_check)
    menu.add("Benchmark getonemarket", bench_getonemarket)
    menu.add("Ophalen historische prijzen", fetch_prices)

    def fetch_prices_polygon_cmd() -> None:
        try:
            run_module("tomic.cli.fetch_prices_polygon")
        except subprocess.CalledProcessError:
            print("❌ Ophalen van historische prijzen mislukt")

    def compute_volstats_polygon_cmd() -> None:
        try:
            run_module("tomic.cli.compute_volstats_polygon")
        except subprocess.CalledProcessError:
            print("❌ Berekenen van volatiliteitsstatistieken mislukt")

    menu.add("Ophalen historische prijzen - polygon", fetch_prices_polygon_cmd)
    menu.add("Bereken volatiliteitsstatistieken - polygon", compute_volstats_polygon_cmd)
    menu.add("Toon historische data", show_history)
    menu.add("Polygon option chain", polygon_chain)
    menu.add("Polygon metrics", polygon_metrics)
    menu.add("Verwerk Flatfile", process_flatfiles_menu)

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
    menu.add(
        "Theoretical value calculator",
        lambda: run_module("tomic.cli.bs_calculator"),
    )
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

    def show_market_info() -> None:
        date_str = today().strftime("%Y-%m-%d")
        summary_dir = Path(cfg.get("IV_DAILY_SUMMARY_DIR", "tomic/data/iv_daily_summary"))
        hv_dir = Path(cfg.get("HISTORICAL_VOLATILITY_DIR", "tomic/data/historical_volatility"))

        rows = []
        for file in summary_dir.glob("*.json"):
            symbol = file.stem
            summaries = [r for r in load_json(file) if r.get("date") == date_str]
            hvs = {r.get("date"): r for r in load_json(hv_dir / f"{symbol}.json")}
            for rec in summaries:
                hv_rec = hvs.get(date_str, {})
                rows.append([
                    symbol,
                    rec.get("atm_iv"),
                    hv_rec.get("hv20"),
                    hv_rec.get("hv30"),
                    hv_rec.get("hv90"),
                    rec.get("iv_rank"),
                    rec.get("iv_percentile"),
                ])

        headers = ["symbol", "iv", "hv20", "hv30", "hv90", "iv_rank", "iv_percentile"]
        print(tabulate(rows, headers=headers, tablefmt="github"))

    menu = Menu("📊 ANALYSE & STRATEGIE")
    menu.add("Trading Plan", lambda: run_module("tomic.cli.trading_plan"))
    menu.add("Portfolio ophalen en tonen", fetch_and_show)
    menu.add("Laatst opgehaalde portfolio tonen", show_saved)
    menu.add("Toon portfolio greeks", show_greeks)
    menu.add("Toon marktinformatie", show_market_info)
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

    def change_bool(key: str) -> None:
        current = getattr(cfg.CONFIG, key)
        val = prompt_yes_no(f"{key}?", current)
        cfg.update({key: val})

    def run_connection_menu() -> None:
        sub = Menu("\U0001F50C Verbinding & API – TWS instellingen en tests")
        sub.add("Pas IB host/poort aan", change_host)
        sub.add("Wijzig client ID", lambda: change_int("IB_CLIENT_ID"))
        sub.add("Test TWS-verbinding", check_ib_connection)
        sub.add("Haal TWS API-versie op", print_api_version)
        sub.run()

    def run_general_menu() -> None:
        sub = Menu("\U0001F4C8 Portfolio & Analyse")
        sub.add("Pas default symbols aan", change_symbols)
        sub.add("Pas interest rate aan", change_rate)
        sub.add(
            "USE_HISTORICAL_IV_WHEN_CLOSED",
            lambda: change_bool("USE_HISTORICAL_IV_WHEN_CLOSED"),
        )
        sub.add(
            "INCLUDE_GREEKS_ONLY_IF_MARKET_OPEN",
            lambda: change_bool("INCLUDE_GREEKS_ONLY_IF_MARKET_OPEN"),
        )
        sub.run()

    def run_logging_menu() -> None:
        sub = Menu("\U0001FAB5 Logging & Gedrag")

        def set_info() -> None:
            cfg.update({"LOG_LEVEL": "INFO"})
            os.environ["TOMIC_LOG_LEVEL"] = "INFO"
            setup_logging()

        def set_debug() -> None:
            cfg.update({"LOG_LEVEL": "DEBUG"})
            os.environ["TOMIC_LOG_LEVEL"] = "DEBUG"
            setup_logging()

        sub.add("Stel logniveau in op INFO", set_info)
        sub.add("Stel logniveau in op DEBUG", set_debug)
        sub.run()

    def run_paths_menu() -> None:
        sub = Menu("\U0001F4C1 Bestandslocaties")
        sub.add("ACCOUNT_INFO_FILE", lambda: change_path("ACCOUNT_INFO_FILE"))
        sub.add("JOURNAL_FILE", lambda: change_path("JOURNAL_FILE"))
        sub.add("POSITIONS_FILE", lambda: change_path("POSITIONS_FILE"))
        sub.add("PORTFOLIO_META_FILE", lambda: change_path("PORTFOLIO_META_FILE"))
        sub.add("VOLATILITY_DB", lambda: change_path("VOLATILITY_DB"))
        sub.add("EXPORT_DIR", lambda: change_path("EXPORT_DIR"))
        sub.run()

    def run_network_menu() -> None:
        sub = Menu("\U0001F310 Netwerk & Snelheid")
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
        sub.add("BID_ASK_TIMEOUT", lambda: change_int("BID_ASK_TIMEOUT"))
        sub.add("MARKET_DATA_TIMEOUT", lambda: change_int("MARKET_DATA_TIMEOUT"))
        sub.add("OPTION_DATA_RETRIES", lambda: change_int("OPTION_DATA_RETRIES"))
        sub.add("OPTION_RETRY_WAIT", lambda: change_int("OPTION_RETRY_WAIT"))
        sub.run()

    def run_option_menu() -> None:
        def show_open_settings() -> None:
            print("Huidige reqMktData instellingen:")
            print(
                f"MKT_GENERIC_TICKS: {cfg.get('MKT_GENERIC_TICKS', '100,101,106')}"
            )
            print(
                f"UNDERLYING_PRIMARY_EXCHANGE: {cfg.get('UNDERLYING_PRIMARY_EXCHANGE', '')}"
            )
            print(
                f"OPTIONS_PRIMARY_EXCHANGE: {cfg.get('OPTIONS_PRIMARY_EXCHANGE', '')}"
            )

        def show_closed_settings() -> None:
            print("Huidige reqHistoricalData instellingen:")
            print(f"USE_HISTORICAL_IV_WHEN_CLOSED: {cfg.get('USE_HISTORICAL_IV_WHEN_CLOSED', True)}")
            print(f"HIST_DURATION: {cfg.get('HIST_DURATION', '1 D')}")
            print(f"HIST_BARSIZE: {cfg.get('HIST_BARSIZE', '1 day')}")
            print(f"HIST_WHAT: {cfg.get('HIST_WHAT', 'TRADES')}")
            print(
                f"UNDERLYING_PRIMARY_EXCHANGE: {cfg.get('UNDERLYING_PRIMARY_EXCHANGE', '')}"
            )
            print(
                f"OPTIONS_PRIMARY_EXCHANGE: {cfg.get('OPTIONS_PRIMARY_EXCHANGE', '')}"
            )

        def run_open_menu() -> None:
            show_open_settings()
            menu = Menu("Markt open – reqMktData")
            menu.add("MKT_GENERIC_TICKS", lambda: change_str("MKT_GENERIC_TICKS"))
            menu.add(
                "UNDERLYING_PRIMARY_EXCHANGE",
                lambda: change_str("UNDERLYING_PRIMARY_EXCHANGE"),
            )
            menu.add(
                "OPTIONS_PRIMARY_EXCHANGE",
                lambda: change_str("OPTIONS_PRIMARY_EXCHANGE"),
            )
            menu.run()

        def run_closed_menu() -> None:
            show_closed_settings()
            menu = Menu("Markt dicht – reqHistoricalData")
            menu.add(
                "USE_HISTORICAL_IV_WHEN_CLOSED",
                lambda: change_bool("USE_HISTORICAL_IV_WHEN_CLOSED"),
            )
            menu.add("HIST_DURATION", lambda: change_str("HIST_DURATION"))
            menu.add("HIST_BARSIZE", lambda: change_str("HIST_BARSIZE"))
            menu.add("HIST_WHAT", lambda: change_str("HIST_WHAT"))
            menu.add(
                "UNDERLYING_PRIMARY_EXCHANGE",
                lambda: change_str("UNDERLYING_PRIMARY_EXCHANGE"),
            )
            menu.add(
                "OPTIONS_PRIMARY_EXCHANGE",
                lambda: change_str("OPTIONS_PRIMARY_EXCHANGE"),
            )
            menu.run()

        sub = Menu("\U0001F4DD Optie-strategie parameters")
        sub.add("STRIKE_RANGE", lambda: change_int("STRIKE_RANGE"))
        sub.add("FIRST_EXPIRY_MIN_DTE", lambda: change_int("FIRST_EXPIRY_MIN_DTE"))
        sub.add("DELTA_MIN", lambda: change_float("DELTA_MIN"))
        sub.add("DELTA_MAX", lambda: change_float("DELTA_MAX"))
        sub.add("AMOUNT_REGULARS", lambda: change_int("AMOUNT_REGULARS"))
        sub.add("AMOUNT_WEEKLIES", lambda: change_int("AMOUNT_WEEKLIES"))
        sub.add("UNDERLYING_EXCHANGE", lambda: change_str("UNDERLYING_EXCHANGE"))
        sub.add(
            "UNDERLYING_PRIMARY_EXCHANGE",
            lambda: change_str("UNDERLYING_PRIMARY_EXCHANGE"),
        )
        sub.add("OPTIONS_EXCHANGE", lambda: change_str("OPTIONS_EXCHANGE"))
        sub.add(
            "OPTIONS_PRIMARY_EXCHANGE",
            lambda: change_str("OPTIONS_PRIMARY_EXCHANGE"),
        )
        sub.add("Markt open – reqMktData", run_open_menu)
        sub.add("Markt dicht – reqHistoricalData", run_closed_menu)
        sub.run()

    menu = Menu("\u2699\ufe0f INSTELLINGEN & CONFIGURATIE")
    menu.add("Portfolio & Analyse", run_general_menu)
    menu.add("Verbinding & API", run_connection_menu)
    menu.add("Netwerk & Snelheid", run_network_menu)
    menu.add("Bestandslocaties", run_paths_menu)
    menu.add("Optie-strategie parameters", run_option_menu)
    menu.add("Logging & Gedrag", run_logging_menu)
    menu.add("Toon volledige configuratie", show_config)
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
