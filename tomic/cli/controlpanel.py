"""Interactive command line interface for TOMIC utilities."""

import subprocess
import sys
from datetime import datetime
import json
from pathlib import Path
import os
from collections import defaultdict

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
from tomic.cli.volatility_recommender import recommend_strategy

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


def find_latest_chain(symbol: str) -> Path | None:
    """Return the most recent option chain CSV for ``symbol``.

    Searches all dated subdirectories of ``EXPORT_DIR`` for files matching
    ``option_chain_{symbol}_*.csv`` and returns the newest match.
    """
    base = Path(cfg.get("EXPORT_DIR", "exports"))
    if not base.exists():
        return None

    pattern = f"option_chain_{symbol.upper()}_*.csv"
    chains = list(base.rglob(pattern))
    if not chains:
        return None
    return max(chains, key=lambda p: p.stat().st_mtime)


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
        symbol = prompt("Ticker symbool: ").strip().upper()
        if not symbol:
            print("❌ Geen symbool opgegeven")
            return

        from tomic.providers.polygon_iv import fetch_polygon_option_chain

        try:
            fetch_polygon_option_chain(symbol)
        except Exception as exc:
            print(f"❌ Ophalen van optionchain mislukt: {exc}")
            return

        base = Path(cfg.get("EXPORT_DIR", "exports"))
        date_dir = base / datetime.now().strftime("%Y%m%d")
        pattern = f"{symbol}_*-optionchainpolygon.csv"
        try:
            files = list(date_dir.glob(pattern)) if date_dir.exists() else []
            latest = max(files, key=lambda f: f.stat().st_mtime) if files else None
        except Exception:
            latest = None

        if latest:
            print(f"✅ Option chain opgeslagen in: {latest.resolve()}")
        else:
            print(f"⚠️ Geen exportbestand gevonden in {date_dir.resolve()}")

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

    def run_github_action() -> None:
        """Run the 'Update price history' GitHub Action locally."""
        try:
            run_module("tomic.cli.fetch_prices_polygon")
        except subprocess.CalledProcessError:
            print("❌ Ophalen van prijzen mislukt")
            return

        try:
            subprocess.run(["git", "status", "--short"], check=True)
            result = subprocess.run(
                ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
            )
            if result.stdout.strip():
                files = []
                files.extend(Path("tomic/data/spot_prices").glob("*.json"))
                files.extend(Path("tomic/data/iv_daily_summary").glob("*.json"))
                files.extend(Path("tomic/data/historical_volatility").glob("*.json"))
                if files:
                    subprocess.run(["git", "add", *[str(f) for f in files]], check=True)
                    subprocess.run(["git", "commit", "-m", "Update price history"], check=True)
                    subprocess.run(["git", "push"], check=True)
            else:
                print("No changes to commit")
        except subprocess.CalledProcessError:
            print("❌ Git-commando mislukt")


    menu = Menu("📁 DATA & MARKTDATA")
    menu.add("OptionChain ophalen via TWS API", export_chain_bulk)
    menu.add("OptionChain ophalen via Polygon API", polygon_chain)
    menu.add("Controleer CSV-kwaliteit", csv_check)
    menu.add("Run GitHub Action lokaal", run_github_action)

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
        summary_dir = Path(cfg.get("IV_DAILY_SUMMARY_DIR", "tomic/data/iv_daily_summary"))
        hv_dir = Path(cfg.get("HISTORICAL_VOLATILITY_DIR", "tomic/data/historical_volatility"))
        spot_dir = Path(cfg.get("PRICE_HISTORY_DIR", "tomic/data/spot_prices"))

        symbols = [s.upper() for s in cfg.get("DEFAULT_SYMBOLS", [])]
        rows: list[list] = []

        for symbol in symbols:
            try:
                summary_data = load_json(summary_dir / f"{symbol}.json")
                hv_data = load_json(hv_dir / f"{symbol}.json")
                spot_data = load_json(spot_dir / f"{symbol}.json")
            except Exception:
                continue

            if not isinstance(summary_data, list) or not isinstance(hv_data, list) or not isinstance(spot_data, list):
                continue

            try:
                summary = sorted(summary_data, key=lambda x: x.get("date", ""), reverse=True)[0]
                hv = sorted(hv_data, key=lambda x: x.get("date", ""), reverse=True)[0]
                spot = sorted(spot_data, key=lambda x: x.get("date", ""), reverse=True)[0]
            except IndexError:
                continue

            rows.append([
                symbol,
                spot.get("close"),
                summary.get("atm_iv"),
                hv.get("hv20"),
                hv.get("hv30"),
                hv.get("hv90"),
                hv.get("hv252"),
                summary.get("iv_rank (HV)"),
                summary.get("iv_percentile (HV)"),
                summary.get("term_m1_m2"),
                summary.get("term_m1_m3"),
                summary.get("skew"),
                spot.get("date"),
            ])

        rows.sort(key=lambda r: r[8] if r[8] is not None else -1, reverse=True)

        def fmt4(val: float | None) -> str:
            return f"{val:.4f}" if val is not None else ""

        def fmt0(val: float | None) -> str:
            return f"{val:.0f}" if val is not None else ""

        formatted_rows = [
            [
                r[0],
                r[1],
                fmt4(r[2]),
                fmt4(r[3]),
                fmt4(r[4]),
                fmt4(r[5]),
                fmt4(r[6]),
                fmt0(r[7]),
                fmt0(r[8]),
                r[9],
                r[10],
                r[11],
                r[12],
            ]
            for r in rows
        ]

        headers = [
            "symbol",
            "spotprice",
            "IV",
            "hv20",
            "hv30",
            "hv90",
            "hv252",
            "iv_rank (HV)",
            "iv_percentile (HV)",
            "term_m1_m2",
            "term_m1_m3",
            "skew",
            "date",
        ]

        print(tabulate(formatted_rows, headers=headers, tablefmt="github"))

        # Strategy recommendation per symbol (grouped by Greek exposure)
        def categorize(exposure: str) -> str:
            if "vega long" in exposure:
                return "Vega Long"
            elif "vega short" in exposure:
                return "Vega Short"
            elif "delta directional" in exposure:
                return "Delta Directioneel"
            elif "delta neutral" in exposure:
                return "Delta Neutraal"
            else:
                return "Overig"

        recs: list[dict[str, object]] = []
        for r in rows:
            metrics = {
                "IV": r[2],
                "HV20": r[3],
                "HV30": r[4],
                "HV90": r[5],
                "HV252": r[6],
                "iv_rank": r[7],
                "iv_percentile": r[8],
                "term_m1_m3": r[10],
                "skew": r[11],
            }
            rec = recommend_strategy(metrics)
            if not rec:
                continue
            crit = ", ".join(rec.get("criteria", []))
            recs.append(
                {
                    "symbol": r[0],
                    "strategy": rec["strategy"],
                    "greeks": rec["greeks"],
                    "indication": rec["indication"],
                    "criteria": crit,
                    "iv_rank": r[7],
                    "iv_percentile": r[8],
                    "category": categorize(rec["greeks"].lower()),
                }
            )

        if recs:
            groups: dict[str, list[dict[str, object]]] = defaultdict(list)
            for rec in recs:
                groups[rec["category"]].append(rec)

            def sort_key(item: dict[str, object]) -> float:
                ivr = item.get("iv_rank")
                ivp = item.get("iv_percentile")
                score = -1.0
                if isinstance(ivr, (int, float)):
                    score = float(ivr)
                elif isinstance(ivp, (int, float)):
                    score = float(ivp)
                return score

            order = ["Vega Short", "Delta Directioneel", "Vega Long", "Delta Neutraal", "Overig"]
            icon_map = {
                "Vega Short": "🎯",
                "Delta Directioneel": "📈",
                "Vega Long": "📉",
                "Delta Neutraal": "⚖️",
                "Overig": "🔍",
            }

            for cat in order:
                items = groups.get(cat)
                if not items:
                    continue
                items.sort(key=sort_key, reverse=True)
                icon = icon_map.get(cat, "🔍")
                print(f"{icon} Focus: {cat}")
                for i, item in enumerate(items, 1):
                    ivr = item.get("iv_rank")
                    ivp = item.get("iv_percentile")
                    if isinstance(ivr, (int, float)):
                        iv_str = f"iv_rank: {ivr:.0f}"
                    elif isinstance(ivp, (int, float)):
                        iv_str = f"iv_pct: {ivp:.0f}"
                    else:
                        iv_str = "iv n.v.t."
                    print(
                        f"{i}. {item['symbol']}: {item['strategy']} — {item['greeks']} ({iv_str})"
                    )
                print()

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
