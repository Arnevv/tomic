"""Interactive command line interface for TOMIC utilities."""

import subprocess
import sys
from datetime import datetime
import json
from pathlib import Path
import os
import csv
from collections import defaultdict
import math
from typing import Any

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
from tomic.logutils import setup_logging, logger
from tomic.analysis.greeks import compute_portfolio_greeks
from tomic.journal.utils import load_json, save_json
from tomic.utils import today
from tomic.cli.volatility_recommender import recommend_strategy, recommend_strategies
from tomic.api.market_export import load_exported_chain
from tomic.cli import services
from tomic.helpers.price_utils import _load_latest_close
from tomic.helpers.price_meta import load_price_meta, save_price_meta
from tomic.polygon_client import PolygonClient
from tomic.strike_selector import StrikeSelector, filter_by_expiry, FilterConfig
from tomic.loader import load_strike_config
from tomic.utils import get_option_mid_price, latest_atr, normalize_leg
from tomic.helpers.csv_utils import normalize_european_number_format
from tomic.helpers.interpolation import interpolate_missing_fields
from tomic.helpers.quality_check import calculate_csv_quality
import pandas as pd
from tomic.metrics import (
    calculate_pos,
    calculate_rom,
    calculate_edge,
    calculate_ev,
)
from tomic.strategy_candidates import generate_strategy_candidates, StrategyProposal
from tomic.bs_calculator import black_scholes
from tomic.scripts.backfill_hv import run_backfill_hv

setup_logging(stdout=True)


POSITIONS_FILE = Path(cfg.get("POSITIONS_FILE", "positions.json"))
ACCOUNT_INFO_FILE = Path(cfg.get("ACCOUNT_INFO_FILE", "account_info.json"))
META_FILE = Path(cfg.get("PORTFOLIO_META_FILE", "portfolio_meta.json"))
STRATEGY_DASHBOARD_MODULE = "tomic.cli.strategy_dashboard"

# Runtime session data shared between menu steps
SESSION_STATE: dict[str, object] = {"evaluated_trades": []}




def _load_spot_from_metrics(directory: Path, symbol: str) -> float | None:
    """Return spot price from a metrics CSV in ``directory`` if available."""
    pattern = f"other_data_{symbol.upper()}_*.csv"
    files = list(directory.glob(pattern))
    if not files:
        return None
    latest = max(files, key=lambda p: p.stat().st_mtime)
    try:
        with latest.open(newline="") as f:
            row = next(csv.DictReader(f))
            spot = row.get("SpotPrice") or row.get("spotprice")
            return float(spot) if spot is not None else None
    except Exception:
        return None


def refresh_spot_price(symbol: str) -> float | None:
    """Fetch and cache the current spot price for ``symbol``.

    Uses :class:`PolygonClient` to retrieve the delayed last trade price and
    caches it under :data:`PRICE_HISTORY_DIR`. When existing data is newer
    than roughly ten minutes the cached value is reused.
    """

    sym = symbol.upper()
    base = Path(cfg.get("PRICE_HISTORY_DIR", "tomic/data/spot_prices"))
    base.mkdir(parents=True, exist_ok=True)
    spot_file = base / f"{sym}.json"

    meta = load_price_meta()
    now = datetime.now()
    ts_str = meta.get(sym)
    if spot_file.exists() and ts_str:
        try:
            ts = datetime.fromisoformat(ts_str)
            if (now - ts).total_seconds() < 600:
                data = load_json(spot_file)
                price = None
                if isinstance(data, dict):
                    price = data.get("price") or data.get("close")
                elif isinstance(data, list) and data:
                    rec = data[-1]
                    price = rec.get("price") or rec.get("close")
                if price is not None:
                    return float(price)
        except Exception:
            pass

    client = PolygonClient()
    try:
        client.connect()
        price = client.fetch_spot_price(sym)
    except Exception as exc:  # pragma: no cover - network issues
        logger.warning(f"⚠️ Spot price fetch failed for {sym}: {exc}")
        price = None
    finally:
        try:
            client.disconnect()
        except Exception:
            pass

    if price is None:
        return None

    save_json({"price": float(price), "timestamp": now.isoformat()}, spot_file)
    meta[sym] = now.isoformat()
    save_price_meta(meta)
    return float(price)


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
        rows = (
            [[rec.get("date"), rec.get("close")] for rec in data[-10:]]
            if isinstance(data, list)
            else []
        )
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

        try:
            path = services.fetch_polygon_chain(symbol)
        except Exception as exc:
            print(f"❌ Ophalen van optionchain mislukt: {exc}")
            return

        if path:
            print(f"✅ Option chain opgeslagen in: {path.resolve()}")
        else:
            date_dir = Path(cfg.get("EXPORT_DIR", "exports")) / datetime.now().strftime("%Y%m%d")
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
            changed = services.git_commit(
                "Update price history",
                Path("tomic/data/spot_prices"),
                Path("tomic/data/iv_daily_summary"),
                Path("tomic/data/historical_volatility"),
            )
            if not changed:
                print("No changes to commit")
        except subprocess.CalledProcessError:
            print("❌ Git-commando mislukt")

    def run_intraday_action() -> None:
        """Run the intraday price update GitHub Action locally."""
        try:
            run_module("tomic.cli.fetch_intraday_polygon")
        except subprocess.CalledProcessError:
            print("❌ Ophalen van intraday prijzen mislukt")
            return

        try:
            changed = services.git_commit(
                "Update intraday prices", Path("tomic/data/spot_prices")
            )
            if not changed:
                print("No changes to commit")
        except subprocess.CalledProcessError:
            print("❌ Git-commando mislukt")

    def fetch_earnings() -> None:
        try:
            run_module("tomic.cli.fetch_earnings_alpha")
        except subprocess.CalledProcessError:
            print("❌ Earnings ophalen mislukt")

    menu = Menu("📁 DATA & MARKTDATA")
    menu.add("OptionChain ophalen via TWS API", export_chain_bulk)
    menu.add("OptionChain ophalen via Polygon API", polygon_chain)
    menu.add("Controleer CSV-kwaliteit", csv_check)
    menu.add("Run GitHub Action lokaal", run_github_action)
    menu.add("Run GitHub Action lokaal - intraday", run_intraday_action)
    menu.add("Backfill historical_volatility obv spotprices", run_backfill_hv)
    menu.add("Fetch Earnings", fetch_earnings)

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
    menu.add("ATR Calculator", lambda: run_module("tomic.cli.atr_calculator"))
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
        view = prompt("Weergavemodus (compact/full/alerts): ", "full").strip().lower()
        try:
            run_module(
                STRATEGY_DASHBOARD_MODULE,
                str(POSITIONS_FILE),
                str(ACCOUNT_INFO_FILE),
                f"--view={view}",
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
        view = prompt("Weergavemodus (compact/full/alerts): ", "full").strip().lower()
        try:
            run_module(
                STRATEGY_DASHBOARD_MODULE,
                str(POSITIONS_FILE),
                str(ACCOUNT_INFO_FILE),
                f"--view={view}",
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
        summary_dir = Path(
            cfg.get("IV_DAILY_SUMMARY_DIR", "tomic/data/iv_daily_summary")
        )
        hv_dir = Path(
            cfg.get("HISTORICAL_VOLATILITY_DIR", "tomic/data/historical_volatility")
        )
        spot_dir = Path(cfg.get("PRICE_HISTORY_DIR", "tomic/data/spot_prices"))
        earnings_dict = load_json(
            cfg.get("EARNINGS_DATES_FILE", "tomic/data/earnings_dates.json")
        )
        if not isinstance(earnings_dict, dict):
            earnings_dict = {}

        symbols = [s.upper() for s in cfg.get("DEFAULT_SYMBOLS", [])]
        rows: list[list] = []

        for symbol in symbols:
            try:
                summary_data = load_json(summary_dir / f"{symbol}.json")
                hv_data = load_json(hv_dir / f"{symbol}.json")
                spot_data = load_json(spot_dir / f"{symbol}.json")
            except Exception:
                continue

            if (
                not isinstance(summary_data, list)
                or not isinstance(hv_data, list)
                or not isinstance(spot_data, list)
            ):
                continue

            try:
                summary = sorted(
                    summary_data, key=lambda x: x.get("date", ""), reverse=True
                )[0]
                hv = sorted(hv_data, key=lambda x: x.get("date", ""), reverse=True)[0]
                spot = sorted(spot_data, key=lambda x: x.get("date", ""), reverse=True)[
                    0
                ]
            except IndexError:
                continue

            next_earn = ""
            earnings_list = earnings_dict.get(symbol)
            if isinstance(earnings_list, list):
                upcoming = []
                for ds in earnings_list:
                    try:
                        d = datetime.strptime(ds, "%Y-%m-%d").date()
                    except Exception:
                        continue
                    if d >= today():
                        upcoming.append(d)
                if upcoming:
                    next_earn = min(upcoming).strftime("%Y-%m-%d")

            rows.append(
                [
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
                    next_earn,
                ]
            )

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
            "next_earnings",
        ]

        print(tabulate(formatted_rows, headers=headers, tablefmt="github"))

        # Strategy recommendation table per symbol
        def categorize(exposure: str) -> str:
            if "vega long" in exposure:
                return "Vega Long"
            if "vega short" in exposure:
                return "Vega Short"
            if (
                "delta directional" in exposure
                or "delta positive" in exposure
                or "delta negative" in exposure
            ):
                return "Delta Directioneel"
            if "delta neutral" in exposure:
                return "Delta Neutraal"
            return "Overig"

        def parse_greeks(expr: str) -> tuple[str, str, str]:
            low = expr.lower()
            vega = "Neutraal"
            theta = "Neutraal"
            delta = "Neutraal"
            if "vega long" in low:
                vega = "Long"
            elif "vega short" in low:
                vega = "Short"
            if "theta long" in low:
                theta = "Long"
            elif "theta short" in low:
                theta = "Short"
            if "delta positive" in low or "delta directional" in low:
                delta = "Richting ↑"
            elif "delta negative" in low:
                delta = "Richting ↓"
            elif "delta neutral" in low:
                delta = "Neutraal"
            return vega, theta, delta

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
            matches = recommend_strategies(metrics)
            for rec in matches:
                crit = ", ".join(rec.get("criteria", []))
                recs.append(
                    {
                        "symbol": r[0],
                        "strategy": rec["strategy"],
                        "greeks": rec["greeks"],
                        "indication": rec.get("indication"),
                        "criteria": crit,
                        "iv_rank": r[7],
                        "iv_percentile": r[8],
                        "skew": r[11],
                        "category": categorize(rec["greeks"].lower()),
                    }
                )

        if recs:
            order = [
                "Vega Short",
                "Delta Directioneel",
                "Vega Long",
                "Delta Neutraal",
                "Overig",
            ]
            order_idx = {cat: i for i, cat in enumerate(order)}
            recs.sort(key=lambda r: (r["symbol"], order_idx.get(r["category"], 99)))

            table_rows: list[list[str]] = []
            for idx, rec in enumerate(recs, 1):
                vega, theta, delta = parse_greeks(rec["greeks"])
                ivr = rec.get("iv_rank")
                iv_val = f"{ivr:.0f}" if isinstance(ivr, (int, float)) else ""
                skew_val = rec.get("skew")
                skew_str = (
                    f"{skew_val:.2f}" if isinstance(skew_val, (int, float)) else ""
                )
                table_rows.append(
                    [
                        idx,
                        rec["symbol"],
                        rec["strategy"],
                        vega,
                        theta,
                        delta,
                        iv_val,
                        skew_str,
                    ]
                )

            print(
                tabulate(
                    table_rows,
                    headers=[
                        "Nr",
                        "Symbool",
                        "Strategie",
                        "Vega",
                        "Theta",
                        "Delta",
                        "IV Rank",
                        "Skew",
                    ],
                    tablefmt="github",
                )
            )

            while True:
                sel = prompt("Selectie (0 om terug): ")
                if sel in {"", "0"}:
                    break
                try:
                    idx = int(sel) - 1
                    chosen = recs[idx]
                except (ValueError, IndexError):
                    print("❌ Ongeldige keuze")
                    continue
                SESSION_STATE.update(
                    {
                        "symbol": chosen.get("symbol"),
                        "strategy": chosen.get("strategy"),
                        "greeks": chosen.get("greeks"),
                        "iv_rank": chosen.get("iv_rank"),
                    }
                )
                print(
                    f"\n🎯 Gekozen strategie: {SESSION_STATE.get('symbol')} – {SESSION_STATE.get('strategy')}\n"
                )
                choose_chain_source()
                return

    def _process_chain(path: Path) -> None:
        if not path.exists():
            print("⚠️ Chain-bestand ontbreekt")
            return

        try:
            df = pd.read_csv(path)
        except Exception as exc:
            print(f"⚠️ Fout bij laden van chain: {exc}")
            return
        df.columns = [c.lower() for c in df.columns]
        df = normalize_european_number_format(
            df,
            [
                "bid",
                "ask",
                "close",
                "iv",
                "delta",
                "gamma",
                "vega",
                "theta",
                "mid",
            ],
        )
        if "expiry" not in df.columns and "expiration" in df.columns:
            df = df.rename(columns={"expiration": "expiry"})
        elif "expiry" in df.columns and "expiration" in df.columns:
            df = df.drop(columns=["expiration"])

        if "expiry" in df.columns:
            df["expiry"] = pd.to_datetime(df["expiry"], errors="coerce").dt.strftime(
                "%Y-%m-%d"
            )
        logger.info(f"Loaded {len(df)} rows from {path}")

        quality = calculate_csv_quality(df)
        min_q = cfg.get("CSV_MIN_QUALITY", 70)
        if quality < min_q:
            print(f"⚠️ CSV kwaliteit {quality:.1f}% lager dan {min_q}%")
        else:
            print(f"CSV kwaliteit {quality:.1f}%")
        logger.info(f"CSV loaded from {path} with quality {quality:.1f}%")
        if not prompt_yes_no("Doorgaan?", False):
            return
        do_interpolate = prompt_yes_no(
            "Wil je delta/iv interpoleren om de data te verbeteren?", False
        )
        if do_interpolate:
            logger.info(
                "Interpolating missing delta/iv values using linear (delta) and spline (iv)"
            )
            df = interpolate_missing_fields(df)
            print("✅ Interpolatie toegepast op ontbrekende delta/iv.")
            logger.info("Interpolation completed successfully")
            quality = calculate_csv_quality(df)
            print(f"Nieuwe CSV kwaliteit {quality:.1f}%")
            new_path = path.with_name(path.stem + "_interpolated.csv")
            df.to_csv(new_path, index=False)
            logger.info(f"Interpolated CSV saved to {new_path}")
            path = new_path
        data = [
            normalize_leg(rec)
            for rec in df.to_dict(orient="records")
        ]
        symbol = str(SESSION_STATE.get("symbol", ""))
        spot_price = refresh_spot_price(symbol)
        if spot_price is None:
            spot_price = _load_spot_from_metrics(path.parent, symbol)
        if spot_price is None:
            spot_price, _ = _load_latest_close(symbol)
        SESSION_STATE["spot_price"] = spot_price
        exp_counts: dict[str, int] = {}
        for row in data:
            exp = row.get("expiry")
            if exp:
                exp_counts[exp] = exp_counts.get(exp, 0) + 1
        for exp, cnt in exp_counts.items():
            logger.info(f"- {exp}: {cnt} options in CSV")

        strat = str(SESSION_STATE.get("strategy", "")).lower().replace(" ", "_")
        rules_path = Path(
            cfg.get("STRIKE_RULES_FILE", "tomic/strike_selection_rules.yaml")
        )
        try:
            config_data = cfg._load_yaml(rules_path)
        except Exception:
            config_data = {}
        rules = load_strike_config(strat, config_data) if config_data else {}
        dte_range = rules.get("dte_range") or [0, 365]
        try:
            dte_tuple = (int(dte_range[0]), int(dte_range[1]))
        except Exception:
            dte_tuple = (0, 365)

        filtered = filter_by_expiry(data, dte_tuple)

        after_counts: dict[str, int] = {}
        for row in filtered:
            exp = row.get("expiry")
            if exp:
                after_counts[exp] = after_counts.get(exp, 0) + 1
        kept_expiries = set(after_counts)
        for exp, cnt in after_counts.items():
            logger.info(f"- {exp}: {cnt} options after DTE filter")
        for exp in exp_counts:
            if exp not in kept_expiries:
                logger.info(f"- {exp}: skipped (outside DTE range)")

        def _val(item, default=None):
            try:
                return float(item)
            except Exception:
                return default

        d_range = rules.get("delta_range", [-1.0, 1.0])
        delta_min = (
            _val(d_range[0], -1.0) if isinstance(d_range, (list, tuple)) else -1.0
        )
        delta_max = (
            _val(d_range[1], 1.0)
            if isinstance(d_range, (list, tuple)) and len(d_range) > 1
            else 1.0
        )

        fc = FilterConfig(
            delta_min=delta_min,
            delta_max=delta_max,
            min_rom=_val(rules.get("min_rom"), 0.0),
            min_edge=_val(rules.get("min_edge"), 0.0),
            min_pos=_val(rules.get("min_pos"), 0.0),
            min_ev=_val(rules.get("min_ev"), 0.0),
            skew_min=_val(rules.get("skew_min"), float("-inf")),
            skew_max=_val(rules.get("skew_max"), float("inf")),
            term_min=_val(rules.get("term_min"), float("-inf")),
            term_max=_val(rules.get("term_max"), float("inf")),
            max_gamma=_val(rules.get("max_gamma"), None),
            max_vega=_val(rules.get("max_vega"), None),
            min_theta=_val(rules.get("min_theta"), None),
        )

        selector = StrikeSelector(config=fc)
        debug_csv = Path(cfg.get("EXPORT_DIR", "exports")) / "PEP_debugfilter.csv"
        selected = selector.select(filtered, debug_csv=debug_csv)

        evaluated: list[dict[str, object]] = []
        for opt in selected:
            mid = get_option_mid_price(opt)
            if mid is None:
                close_val = opt.get("close")
                try:
                    close_f = float(close_val)
                except Exception:
                    close_f = 0.0
                if close_f > 0:
                    mid = close_f
                    logger.debug(
                        f"Using close as mid for {opt.get('strike')} {opt.get('type')}"
                    )
            try:
                model = (
                    float(opt.get("modelprice"))
                    if opt.get("modelprice") is not None
                    else None
                )
            except Exception:
                model = None
            if model is None:
                try:
                    iv = float(opt.get("iv")) if float(opt.get("iv", 0)) > 0 else None
                except Exception:
                    iv = None
                try:
                    strike_val = float(opt.get("strike"))
                except Exception:
                    strike_val = None
                expiry_str = str(opt.get("expiry")) if opt.get("expiry") else None
                opt_type = str(opt.get("type") or opt.get("right", "")).upper()[:1]
                if (
                    spot_price is not None
                    and iv is not None
                    and strike_val is not None
                    and expiry_str
                    and opt_type in {"C", "P"}
                ):
                    try:
                        exp = None
                        for fmt in ("%Y%m%d", "%Y-%m-%d"):
                            try:
                                exp = datetime.strptime(expiry_str, fmt).date()
                                break
                            except Exception:
                                continue
                        if exp is None:
                            raise ValueError("invalid expiry format")
                        dte_calc = max((exp - datetime.now().date()).days, 0)
                        model = round(
                            black_scholes(
                                opt_type,
                                float(spot_price),
                                strike_val,
                                dte_calc,
                                iv,
                                cfg.get("INTEREST_RATE", 0.05),
                                0.0,
                            ),
                            2,
                        )
                    except Exception:
                        model = None
            try:
                margin = (
                    float(opt.get("marginreq"))
                    if opt.get("marginreq") is not None
                    else None
                )
            except Exception:
                margin = None
            if margin is None:
                try:
                    strike_val = float(opt.get("strike"))
                except Exception:
                    strike_val = None
                base = float(spot_price) if spot_price is not None else strike_val
                margin = round(base * 100 * 0.2, 2) if base else 350.0
            try:
                delta = float(opt.get("delta"))
            except Exception:
                delta = None

            pos = calculate_pos(delta) if delta is not None else None
            rom = None
            ev = None
            edge = None
            if mid is not None and margin is not None:
                rom = calculate_rom(mid * 100, margin)
            if model is not None and mid is not None:
                edge = calculate_edge(model, mid)
            if model is not None:
                opt["model"] = model
            if None not in (pos, mid, margin):
                ev = calculate_ev(pos, mid * 100, -margin)

            res = {
                "symbol": SESSION_STATE.get("symbol"),
                "expiry": opt.get("expiry"),
                "strike": opt.get("strike"),
                "type": opt.get("type"),
                "delta": delta,
                "mid": mid,
                "model": model,
                "margin": margin,
                "pos": pos,
                "rom": rom,
                "edge": edge,
                "ev": ev,
            }
            normalize_leg(res)
            evaluated.append(res)

        SESSION_STATE.setdefault("evaluated_trades", []).extend(evaluated)
        if evaluated:
            close_price, close_date = _load_latest_close(symbol)
            if close_price is not None and close_date:
                print(f"Close {close_date}: {close_price}")
            atr_val = latest_atr(symbol)
            if atr_val is not None:
                print(f"ATR: {atr_val:.2f}")
            else:
                print("ATR: n.v.t.")

            rows = []
            for row in evaluated[:10]:
                rows.append(
                    [
                        row.get("expiry"),
                        row.get("strike"),
                        row.get("type"),
                        (
                            f"{row.get('delta'):+.2f}"
                            if row.get("delta") is not None
                            else ""
                        ),
                        f"{row.get('edge'):.2f}" if row.get("edge") is not None else "",
                        f"{row.get('pos'):.1f}%" if row.get("pos") is not None else "",
                    ]
                )
            print(
                tabulate(
                    rows,
                    headers=[
                        "Expiry",
                        "Strike",
                        "Type",
                        "Delta",
                        "Edge",
                        "PoS",
                    ],
                    tablefmt="github",
                )
            )
            if prompt_yes_no("Opslaan naar CSV?", False):
                _save_trades(evaluated)
            if prompt_yes_no("Doorgaan naar strategie voorstellen?", False):
                atr_val = latest_atr(symbol) or 0.0
                spot_for_strats = refresh_spot_price(symbol)
                if spot_for_strats is None:
                    spot_for_strats = _load_spot_from_metrics(path.parent, symbol)
                if spot_for_strats is None:
                    spot_for_strats, _ = _load_latest_close(symbol)
                SESSION_STATE["spot_price"] = spot_for_strats
                if spot_for_strats is not None:
                    print(f"Spotprice: {spot_for_strats:.2f}")
                else:
                    print("Spotprice: n/a")
                proposals, reason = generate_strategy_candidates(
                    symbol,
                    strat,
                    selected,
                    atr_val,
                    config_data or {},
                    spot_for_strats,
                    interactive_mode=True,
                )
                if proposals:
                    rom_w = cfg.get("SCORE_WEIGHT_ROM", 0.5)
                    pos_w = cfg.get("SCORE_WEIGHT_POS", 0.3)
                    ev_w = cfg.get("SCORE_WEIGHT_EV", 0.2)
                    print(
                        f"Scoregewichten: ROM {rom_w*100:.0f}% | PoS {pos_w*100:.0f}% | EV {ev_w*100:.0f}%"
                    )
                    rows2 = []
                    warn_edge = False
                    for prop in proposals:
                        legs_desc = "; ".join(
                            f"{'S' if leg.get('position',0)<0 else 'L'}{leg.get('type')}{leg.get('strike')} {leg.get('expiry', '?')}"
                            for leg in prop.legs
                        )
                        for leg in prop.legs:
                            if leg.get("edge") is None:
                                logger.debug(
                                    f"[EDGE missing] {leg.get('position')} {leg.get('type')} {leg.get('strike')} {leg.get('expiry')}"
                                )
                        if any(leg.get("edge") is None for leg in prop.legs):
                            warn_edge = True
                        edge_vals = [
                            float(leg.get("edge"))
                            for leg in prop.legs
                            if leg.get("edge") is not None
                        ]
                        if not edge_vals:
                            edge_display = "—"
                        elif len(edge_vals) < len(prop.legs):
                            mn = min(edge_vals)
                            if mn < 0:
                                edge_display = f"min={mn:.2f}"
                            else:
                                edge_display = (
                                    f"avg={sum(edge_vals)/len(edge_vals):.2f}"
                                )
                        else:
                            edge_display = f"{sum(edge_vals)/len(edge_vals):.2f}"
                        rows2.append(
                            [
                                f"{prop.score:.2f}" if prop.score is not None else "—",
                                f"{prop.pos:.1f}" if prop.pos is not None else "—",
                                f"{prop.ev:.2f}" if prop.ev is not None else "—",
                                f"{prop.rom:.2f}" if prop.rom is not None else "—",
                                edge_display,
                                legs_desc,
                            ]
                        )
                    print(
                        tabulate(
                            rows2,
                            headers=["Score", "PoS", "EV", "ROM", "Edge", "Legs"],
                            tablefmt="github",
                        )
                    )
                    if warn_edge:
                        print("⚠️ Eén of meerdere edges niet beschikbaar")
                    while True:
                        sel = prompt("Kies voorstel (0 om terug): ")
                        if sel in {"", "0"}:
                            break
                        try:
                            idx = int(sel) - 1
                            chosen_prop = proposals[idx]
                        except (ValueError, IndexError):
                            print("❌ Ongeldige keuze")
                            continue
                        _show_proposal_details(chosen_prop)
                        break
                else:
                    msg = "⚠️ Geen voorstellen gevonden"
                    if reason:
                        if isinstance(reason, list):
                            for r in reason:
                                msg += f"\n• {r}"
                        else:
                            msg += f"\n• {reason}"
                    print(msg)
        else:
            print("⚠️ Geen geschikte strikes gevonden.")
            print("➤ Controleer of de juiste expiraties beschikbaar zijn in de chain.")
            print("➤ Of pas je selectiecriteria aan in strike_selection_rules.yaml.")

    def _show_proposal_details(proposal: StrategyProposal) -> None:
        rows: list[list[str]] = []
        warns: list[str] = []
        for leg in proposal.legs:
            if leg.get("edge") is None:
                logger.debug(
                    f"[EDGE missing] {leg.get('position')} {leg.get('type')} {leg.get('strike')} {leg.get('expiry')}"
                )
            bid = leg.get("bid")
            ask = leg.get("ask")
            mid = leg.get("mid")
            if bid is None or ask is None:
                warns.append(f"⚠️ Bid/ask ontbreekt voor strike {leg.get('strike')}")
            if mid is not None:
                try:
                    mid_f = float(mid)
                    if bid is not None and math.isclose(
                        mid_f, float(bid), abs_tol=1e-6
                    ):
                        warns.append(
                            f"⚠️ Midprijs gelijk aan bid voor strike {leg.get('strike')}"
                        )
                    if ask is not None and math.isclose(
                        mid_f, float(ask), abs_tol=1e-6
                    ):
                        warns.append(
                            f"⚠️ Midprijs gelijk aan ask voor strike {leg.get('strike')}"
                        )
                except Exception:
                    pass

            rows.append(
                [
                    leg.get("expiry"),
                    leg.get("strike"),
                    leg.get("type"),
                    "S" if leg.get("position", 0) < 0 else "L",
                    f"{bid:.2f}" if bid is not None else "—",
                    f"{ask:.2f}" if ask is not None else "—",
                    f"{mid:.2f}" if mid is not None else "—",
                    (
                        f"{leg.get('delta', 0):+.2f}"
                        if leg.get("delta") is not None
                        else ""
                    ),
                    (
                        f"{leg.get('theta', 0):+.2f}"
                        if leg.get("theta") is not None
                        else ""
                    ),
                    f"{leg.get('vega', 0):+.2f}" if leg.get("vega") is not None else "",
                    f"{leg.get('edge'):.2f}" if leg.get("edge") is not None else "—",
                ]
            )
        missing_edge = any(leg.get("edge") is None for leg in proposal.legs)

        print(
            tabulate(
                rows,
                headers=[
                    "Expiry",
                    "Strike",
                    "Type",
                    "Pos",
                    "Bid",
                    "Ask",
                    "Mid",
                    "Δ",
                    "Θ",
                    "V",
                    "Edge",
                ],
                tablefmt="github",
            )
        )
        if missing_edge:
            warns.append("⚠️ Eén of meerdere edges niet beschikbaar")
        for warning in warns:
            print(warning)
        if missing_edge and not cfg.get("ALLOW_INCOMPLETE_METRICS", False):
            if not prompt_yes_no(
                "⚠️ Deze strategie bevat onvolledige edge-informatie. Toch accepteren?",
                False,
            ):
                return
        print(f"Credit: {proposal.credit:.2f}")
        if proposal.margin is not None:
            print(f"Margin: {proposal.margin:.2f}")
        else:
            print("Margin: —")
        max_win = (
            f"{proposal.max_profit:.2f}" if proposal.max_profit is not None else "—"
        )
        print(f"Max win: {max_win}")
        max_loss = f"{proposal.max_loss:.2f}" if proposal.max_loss is not None else "—"
        print(f"Max loss: {max_loss}")
        if proposal.breakevens:
            be = ", ".join(f"{b:.2f}" for b in proposal.breakevens)
            print(f"Breakevens: {be}")
        pos_str = f"{proposal.pos:.2f}" if proposal.pos is not None else "—"
        print(f"PoS: {pos_str}")
        rom_str = f"{proposal.rom:.2f}" if proposal.rom is not None else "—"
        print(f"ROM: {rom_str}")
        ev_str = f"{proposal.ev:.2f}" if proposal.ev is not None else "—"
        print(f"EV: {ev_str}")
        if prompt_yes_no("Voorstel opslaan naar CSV?", False):
            _export_proposal_csv(proposal)
        if prompt_yes_no("Voorstel opslaan naar JSON?", False):
            _export_proposal_json(proposal)
        journal = _proposal_journal_text(proposal)
        print("\nJournal entry voorstel:\n" + journal)

    def _save_trades(trades: list[dict[str, object]]) -> None:
        symbol = str(SESSION_STATE.get("symbol", "SYMB"))
        strat = str(SESSION_STATE.get("strategy", "strategy")).replace(" ", "_")
        expiry = str(trades[0].get("expiry", "")) if trades else ""
        base = Path(cfg.get("EXPORT_DIR", "exports")) / datetime.now().strftime(
            "%Y%m%d"
        )
        base.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%H%M%S")
        path = base / f"trade_candidates_{symbol}_{strat}_{expiry}_{ts}.csv"
        fieldnames = [k for k in trades[0].keys() if k not in {"rom", "ev"}]
        with path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in trades:
                out: dict[str, object] = {}
                for k, v in row.items():
                    if k not in fieldnames:
                        continue
                    if k in {
                        "pos",
                        "rom",
                        "ev",
                        "edge",
                        "mid",
                        "model",
                        "delta",
                        "margin",
                    }:
                        try:
                            out[k] = f"{float(v):.2f}"
                        except Exception:
                            out[k] = ""
                    else:
                        out[k] = v
                writer.writerow(out)
        print(f"✅ Trades opgeslagen in: {path.resolve()}")

    def _export_proposal_csv(proposal: StrategyProposal) -> None:
        symbol = str(SESSION_STATE.get("symbol", "SYMB"))
        strat = str(SESSION_STATE.get("strategy", "strategy")).replace(" ", "_")
        base = Path(cfg.get("EXPORT_DIR", "exports")) / datetime.now().strftime(
            "%Y%m%d"
        )
        base.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%H%M%S")
        path = base / f"strategy_proposal_{symbol}_{strat}_{ts}.csv"
        with path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "expiry",
                    "strike",
                    "type",
                    "position",
                    "bid",
                    "ask",
                    "mid",
                    "delta",
                    "theta",
                    "vega",
                    "edge",
                    "manual_override",
                ]
            )
            for leg in proposal.legs:
                writer.writerow(
                    [
                        leg.get("expiry"),
                        leg.get("strike"),
                        leg.get("type"),
                        leg.get("position"),
                        leg.get("bid"),
                        leg.get("ask"),
                        leg.get("mid"),
                        leg.get("delta"),
                        leg.get("theta"),
                        leg.get("vega"),
                        leg.get("edge"),
                        leg.get("manual_override"),
                    ]
                )
            writer.writerow([])
            writer.writerow(["credit", proposal.credit])
            writer.writerow(["max_loss", proposal.max_loss])
            if proposal.breakevens:
                writer.writerow(["breakevens", *proposal.breakevens])
        print(f"✅ Voorstel opgeslagen in: {path.resolve()}")
    def _load_acceptance_criteria(strategy: str) -> dict[str, Any]:
        """Return current acceptance criteria for ``strategy``."""
        rules_path = Path(
            cfg.get("STRIKE_RULES_FILE", "tomic/strike_selection_rules.yaml")
        )
        try:
            config_data = cfg._load_yaml(rules_path)
        except Exception:
            config_data = {}
        rules = load_strike_config(strategy, config_data) if config_data else {}
        try:
            min_rom = float(rules.get("min_rom")) if rules.get("min_rom") is not None else None
        except Exception:
            min_rom = None
        return {
            "min_rom": min_rom,
            "min_pos": 0.0,
            "require_positive_ev": True,
            "allow_missing_edge": bool(cfg.get("ALLOW_INCOMPLETE_METRICS", False)),
        }

    def _load_portfolio_context() -> tuple[dict[str, Any], bool]:
        """Return portfolio context and availability flag."""
        ctx = {
            "net_delta": None,
            "net_theta": None,
            "net_vega": None,
            "margin_used": None,
            "positions_open": None,
        }
        if not POSITIONS_FILE.exists() or not ACCOUNT_INFO_FILE.exists():
            return ctx, False
        try:
            positions = json.loads(POSITIONS_FILE.read_text())
            account = json.loads(ACCOUNT_INFO_FILE.read_text())
            greeks = compute_portfolio_greeks(positions)
            ctx.update(
                {
                    "net_delta": greeks.get("Delta"),
                    "net_theta": greeks.get("Theta"),
                    "net_vega": greeks.get("Vega"),
                    "positions_open": len(positions),
                    "margin_used": float(account.get("FullInitMarginReq"))
                    if account.get("FullInitMarginReq") is not None
                    else None,
                }
            )
        except Exception:
            return ctx, False
        return ctx, True

    def _export_proposal_json(proposal: StrategyProposal) -> None:
        symbol = str(SESSION_STATE.get("symbol", "SYMB"))
        strategy_name = str(SESSION_STATE.get("strategy", "strategy"))
        strat_file = strategy_name.replace(" ", "_")
        base = Path(cfg.get("EXPORT_DIR", "exports")) / datetime.now().strftime(
            "%Y%m%d"
        )
        base.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%H%M%S")
        path = base / f"strategy_proposal_{symbol}_{strat_file}_{ts}.json"

        accept = _load_acceptance_criteria(strat_file)
        portfolio_ctx, portfolio_available = _load_portfolio_context()
        spot_price = SESSION_STATE.get("spot_price")

        earnings_dict = load_json(
            cfg.get("EARNINGS_DATES_FILE", "tomic/data/earnings_dates.json")
        )
        next_earn = None
        if isinstance(earnings_dict, dict):
            earnings_list = earnings_dict.get(symbol)
            if isinstance(earnings_list, list):
                upcoming: list[datetime] = []
                for ds in earnings_list:
                    try:
                        d = datetime.strptime(ds, "%Y-%m-%d").date()
                    except Exception:
                        continue
                    if d >= today():
                        upcoming.append(d)
                if upcoming:
                    next_earn = min(upcoming).strftime("%Y-%m-%d")

        data = {
            "symbol": symbol,
            "spot_price": spot_price,
            "strategy": strat_file,
            "next_earnings_date": next_earn,
            "legs": proposal.legs,
            "metrics": {
                "credit": proposal.credit,
                "margin": proposal.margin,
                "pos": proposal.pos,
                "rom": proposal.rom,
                "ev": proposal.ev,
                "average_edge": proposal.edge,
                "max_profit": proposal.max_profit
                if proposal.max_profit is not None
                else "unlimited",
                "max_loss": proposal.max_loss
                if proposal.max_loss is not None
                else "unlimited",
                "breakevens": proposal.breakevens or [],
                "score": proposal.score,
                "missing_data": {
                    "missing_bidask": any(
                        (
                            (b := l.get("bid")) is None
                            or (isinstance(b, (int, float)) and (math.isnan(b) or b <= 0))
                        )
                        or (
                            (a := l.get("ask")) is None
                            or (isinstance(a, (int, float)) and (math.isnan(a) or a <= 0))
                        )
                        for l in proposal.legs
                    ),
                    "missing_edge": proposal.edge is None,
                    "fallback_mid": any(
                        l.get("mid_fallback") == "close"
                        or (
                            l.get("mid") is not None
                            and (
                                (
                                    (b := l.get("bid")) is None
                                    or (
                                        isinstance(b, (int, float))
                                        and (math.isnan(b) or b <= 0)
                                    )
                                )
                                or (
                                    (a := l.get("ask")) is None
                                    or (
                                        isinstance(a, (int, float))
                                        and (math.isnan(a) or a <= 0)
                                    )
                                )
                            )
                        )
                        for l in proposal.legs
                    ),
                },
            },
            "tomic_acceptance_criteria": accept,
            "portfolio_context": portfolio_ctx,
            "portfolio_context_available": portfolio_available,
        }
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"✅ Voorstel opgeslagen in: {path.resolve()}")

    def _proposal_journal_text(proposal: StrategyProposal) -> str:
        margin_str = f"{proposal.margin:.2f}" if proposal.margin is not None else "—"
        pos_str = f"{proposal.pos:.2f}" if proposal.pos is not None else "—"
        rom_str = f"{proposal.rom:.2f}" if proposal.rom is not None else "—"
        ev_str = f"{proposal.ev:.2f}" if proposal.ev is not None else "—"
        lines = [
            f"Symbol: {SESSION_STATE.get('symbol')}",
            f"Strategy: {SESSION_STATE.get('strategy')}",
            f"Credit: {proposal.credit:.2f}",
            f"Margin: {margin_str}",
            f"ROM: {rom_str}",
            f"PoS: {pos_str}",
            f"EV: {ev_str}",
        ]
        for leg in proposal.legs:
            side = "Short" if leg.get("position", 0) < 0 else "Long"
            mid = leg.get("mid")
            mid_str = f"{mid:.2f}" if mid is not None else ""
            lines.append(
                f"{side} {leg.get('type')} {leg.get('strike')} {leg.get('expiry')} @ {mid_str}"
            )
        return "\n".join(lines)

    def choose_chain_source() -> None:
        symbol = SESSION_STATE.get("symbol")
        if not symbol:
            print("⚠️ Geen strategie geselecteerd")
            return

        def use_ib() -> None:
            path = services.export_chain(str(symbol))
            if not path:
                print("⚠️ Geen chain gevonden")
                return
            _process_chain(path)

        def use_polygon() -> None:
            path = services.fetch_polygon_chain(str(symbol))
            if not path:
                print("⚠️ Geen polygon chain gevonden")
                return
            _process_chain(path)

        def manual() -> None:
            p = prompt("Pad naar CSV: ")
            if not p:
                return
            _process_chain(Path(p))

        menu = Menu("Chain ophalen")
        menu.add("Download nieuwe chain via TWS", use_ib)
        menu.add("Download nieuwe chain via Polygon", use_polygon)
        menu.add("CSV handmatig kiezen", manual)
        menu.run()

    menu = Menu("📊 ANALYSE & STRATEGIE")
    menu.add("Trading Plan", lambda: run_module("tomic.cli.trading_plan"))
    menu.add("Portfolio ophalen en tonen", fetch_and_show)
    menu.add("Laatst opgehaalde portfolio tonen", show_saved)
    menu.add("Toon portfolio greeks", show_greeks)
    menu.add("Toon marktinformatie", show_market_info)
    menu.add("Earnings-informatie", lambda: run_module("tomic.cli.earnings_info"))
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
        sub = Menu("\U0001f50c Verbinding & API – TWS instellingen en tests")
        sub.add("Pas IB host/poort aan", change_host)
        sub.add("Wijzig client ID", lambda: change_int("IB_CLIENT_ID"))
        sub.add("Test TWS-verbinding", check_ib_connection)
        sub.add("Haal TWS API-versie op", print_api_version)
        sub.run()

    def run_general_menu() -> None:
        sub = Menu("\U0001f4c8 Portfolio & Analyse")
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
        sub = Menu("\U0001fab5 Logging & Gedrag")

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
        sub = Menu("\U0001f4c1 Bestandslocaties")
        sub.add("ACCOUNT_INFO_FILE", lambda: change_path("ACCOUNT_INFO_FILE"))
        sub.add("JOURNAL_FILE", lambda: change_path("JOURNAL_FILE"))
        sub.add("POSITIONS_FILE", lambda: change_path("POSITIONS_FILE"))
        sub.add("PORTFOLIO_META_FILE", lambda: change_path("PORTFOLIO_META_FILE"))
        sub.add("VOLATILITY_DB", lambda: change_path("VOLATILITY_DB"))
        sub.add("EXPORT_DIR", lambda: change_path("EXPORT_DIR"))
        sub.run()

    def run_network_menu() -> None:
        sub = Menu("\U0001f310 Netwerk & Snelheid")
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
            print(f"MKT_GENERIC_TICKS: {cfg.get('MKT_GENERIC_TICKS', '100,101,106')}")
            print(
                f"UNDERLYING_PRIMARY_EXCHANGE: {cfg.get('UNDERLYING_PRIMARY_EXCHANGE', '')}"
            )
            print(
                f"OPTIONS_PRIMARY_EXCHANGE: {cfg.get('OPTIONS_PRIMARY_EXCHANGE', '')}"
            )

        def show_closed_settings() -> None:
            print("Huidige reqHistoricalData instellingen:")
            print(
                f"USE_HISTORICAL_IV_WHEN_CLOSED: {cfg.get('USE_HISTORICAL_IV_WHEN_CLOSED', True)}"
            )
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

        sub = Menu("\U0001f4dd Optie-strategie parameters")
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
