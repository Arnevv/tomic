"""Interactive command line interface for TOMIC utilities."""

import argparse
import subprocess
import sys
from datetime import datetime, date
import json
from pathlib import Path
import os
import csv
import inspect
from typing import Any, Mapping, Sequence

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
from tomic.config import save_symbols
from tomic.logutils import capture_combo_evaluations, normalize_reason, setup_logging, logger
from tomic.analysis.greeks import compute_portfolio_greeks
from tomic.journal.utils import load_json, save_json
from tomic.utils import today
from tomic.analysis.volatility_fetcher import fetch_volatility_metrics
from tomic.analysis.market_overview import build_market_overview
from tomic.api.market_export import load_exported_chain
from tomic.cli.app_services import ControlPanelServices, create_controlpanel_services
from tomic.cli.controlpanel_session import ControlPanelSession
from tomic.cli.rejections.handlers import build_rejection_summary
from tomic.cli.exports.menu import build_export_menu
from tomic.cli.portfolio.menu_flow import (
    process_chain as portfolio_process_chain,
    run_market_scan as portfolio_run_market_scan,
    show_market_overview as portfolio_show_market_overview,
)
from tomic.exports import (
    export_proposal_csv,
    export_proposal_json,
    proposal_journal_text,
    refresh_spot_price,
    load_spot_from_metrics,
    spot_from_chain,
)
from tomic.helpers.price_utils import _load_latest_close
from tomic.metrics import calculate_edge, calculate_ev, calculate_pos, calculate_rom
import pandas as pd
from tomic.services.strategy_pipeline import StrategyProposal, RejectionSummary
from tomic.services.ib_marketdata import fetch_quote_snapshot, SnapshotResult
from tomic.services.order_submission import (
    OrderSubmissionService,
    prepare_order_instructions,
)
from tomic.strategy.reasons import ReasonCategory, ReasonDetail
from tomic.strategy_candidates import generate_strategy_candidates
from tomic.core import config as runtime_config
from tomic.criteria import load_criteria
from tomic.reporting import (
    EvaluationSummary,
    format_dtes,
    format_money,
    format_reject_reasons,
    summarize_evaluations,
    to_float,
)
from tomic.reporting.rejections import (
    ExpiryBreakdown,
    _format_leg_summary as _reporting_format_leg_summary,
)
from tomic.services.pipeline_refresh import (
    RefreshSource,
    Proposal as RefreshProposal,
)
from tomic.services.proposal_details import (
    build_proposal_core,
    build_proposal_viewmodel,
)
from tomic.formatting.portfolio_tables import build_factsheet_table
from tomic.formatting.table_builders import (
    proposal_earnings_table,
    proposal_legs_table,
    proposal_summary_table,
)

setup_logging(stdout=True)


POSITIONS_FILE = Path(cfg.get("POSITIONS_FILE", "positions.json"))
ACCOUNT_INFO_FILE = Path(cfg.get("ACCOUNT_INFO_FILE", "account_info.json"))
META_FILE = Path(cfg.get("PORTFOLIO_META_FILE", "portfolio_meta.json"))
STRATEGY_DASHBOARD_MODULE = "tomic.cli.strategy_dashboard"


def _format_leg_summary(legs: Sequence[Mapping[str, Any]] | None) -> str:
    """Expose leg summary formatting used in tests and CLI flows."""

    return _reporting_format_leg_summary(legs)


def _format_reject_reasons(summary: EvaluationSummary) -> str:
    """Return a formatted summary of rejection reasons."""

    return format_reject_reasons(summary)


def _strike_selector_factory(*args, **kwargs):
    try:
        selector = StrikeSelector(*args, **kwargs)
    except TypeError:
        # Compatibility for tests that monkeypatch ``StrikeSelector`` with a simple
        # callable that only accepts the configuration positional argument.
        if kwargs:
            selector = StrikeSelector(kwargs.get("config"))
        else:
            raise
    return _wrap_selector(selector)


def _wrap_selector(selector):
    select = getattr(selector, "select", None)
    if not callable(select):
        return selector
    try:
        params = inspect.signature(select).parameters
    except (TypeError, ValueError):
        params = {}
    if "dte_range" not in params:

        def _adapted_select(data, *, dte_range=None, debug_csv=None, return_info=False):
            return select(data, debug_csv=debug_csv, return_info=return_info)

        selector.select = _adapted_select  # type: ignore[attr-defined]
    return selector




def _print_evaluation_overview(symbol: str, spot: float | None, summary: EvaluationSummary | None) -> None:
    if summary is None or summary.total <= 0:
        return
    sym = symbol.upper() if symbol else "—"
    if isinstance(spot, (int, float)) and spot > 0:
        header = f"Evaluatieoverzicht: {sym} @ {spot:.2f}"
    else:
        header = f"Evaluatieoverzicht: {sym}"
    print(header)
    print(f"Totaal combinaties: {summary.total}")
    if summary.expiries:
        print("Expiry breakdown:")
        for breakdown in summary.sorted_expiries():
            print(f"• {breakdown.label}: {breakdown.format_counts()}")
    print(f"Top reason for reject: {format_reject_reasons(summary)}")


def _generate_with_capture(
    session: ControlPanelSession, *args: Any, **kwargs: Any
):
    session.clear_combo_results()
    with capture_combo_evaluations() as captured:
        try:
            result = generate_strategy_candidates(*args, **kwargs)
        finally:
            summary = summarize_evaluations(captured)
            session.set_combo_results(captured, summary)
    return result


def _create_services(session: ControlPanelSession) -> ControlPanelServices:
    return create_controlpanel_services(
        strike_selector_factory=_strike_selector_factory,
        strategy_generator=lambda *args, **kwargs: _generate_with_capture(
            session, *args, **kwargs
        ),
    )


SHOW_REASONS = False


def _show_proposal_details(
    session: ControlPanelSession, proposal: StrategyProposal
) -> None:
    criteria_cfg = load_criteria()
    symbol = (
        str(session.symbol or proposal.legs[0].get("symbol", ""))
        if proposal.legs
        else str(session.symbol or "")
    )
    symbol = symbol or None
    spot_price = session.spot_price
    fetch_only_mode = bool(cfg.get("IB_FETCH_ONLY", False))
    refresh_result: SnapshotResult | None = None
    should_fetch = fetch_only_mode or prompt_yes_no("Haal orderinformatie van IB op?", True)
    if should_fetch:
        try:
            refresh_result = fetch_quote_snapshot(
                proposal,
                criteria=criteria_cfg,
                spot_price=spot_price if isinstance(spot_price, (int, float)) else None,
                timeout=float(cfg.get("MARKET_DATA_TIMEOUT", 15)),
            )
            proposal = refresh_result.proposal
        except Exception as exc:
            logger.exception("IB marktdata refresh mislukt: %s", exc)
            print(f"❌ Marktdata ophalen mislukt: {exc}")

    entry_stub: dict[str, Any] = {"symbol": symbol} if symbol else {}
    core = build_proposal_core(proposal, symbol=symbol, entry=entry_stub)
    candidate = RefreshProposal(
        proposal=proposal,
        source=RefreshSource(index=0, entry=entry_stub, symbol=symbol),
        reasons=list(refresh_result.reasons) if refresh_result else [],
        missing_quotes=list(refresh_result.missing_quotes) if refresh_result else [],
        core=core,
        accepted=refresh_result.accepted if refresh_result else None,
    )

    earnings_ctx = {
        "symbol": symbol,
        "next_earnings": session.next_earnings,
        "days_until_earnings": session.days_until_earnings,
    }
    vm = build_proposal_viewmodel(candidate, earnings_ctx)

    leg_headers, leg_rows = proposal_legs_table(vm)
    if leg_rows:
        print(tabulate(leg_rows, headers=leg_headers, tablefmt="github"))

    summary_headers, summary_rows = proposal_summary_table(vm)
    if summary_rows:
        print(tabulate(summary_rows, headers=summary_headers, tablefmt="github"))

    earnings_headers, earnings_rows = proposal_earnings_table(vm)
    if earnings_rows:
        print(tabulate(earnings_rows, headers=earnings_headers, tablefmt="github"))

    for warning in vm.warnings:
        print(warning)

    acceptance_failed = vm.accepted is False
    if acceptance_failed:
        print("❌ Acceptatiecriteria niet gehaald na IB-refresh.")
        for detail in vm.reasons:
            msg = getattr(detail, "message", None) or getattr(detail, "code", None)
            if not msg:
                msg = str(detail)
            print(f"  - {msg}")

    if vm.has_missing_edge and not cfg.get("ALLOW_INCOMPLETE_METRICS", False):
        if not prompt_yes_no(
            "⚠️ Deze strategie bevat onvolledige edge-informatie. Toch accepteren?",
            False,
        ):
            return

    if prompt_yes_no("Voorstel opslaan naar CSV?", False):
        path = export_proposal_csv(session, proposal)
        print(f"✅ Voorstel opgeslagen in: {path.resolve()}")
    if prompt_yes_no("Voorstel opslaan naar JSON?", False):
        path = export_proposal_json(session, proposal)
        print(f"✅ Voorstel opgeslagen in: {path.resolve()}")

    can_send_order = not acceptance_failed and not fetch_only_mode
    if can_send_order and prompt_yes_no("Order naar IB sturen?", False):
        _submit_ib_order(session, proposal, symbol=symbol)
    elif fetch_only_mode:
        print("ℹ️ fetch_only modus actief – orders worden niet verstuurd.")

    proposal_strategy = getattr(proposal, "strategy", None)
    strategy_label = str(session.strategy or proposal_strategy or "") or None
    journal_text = proposal_journal_text(
        session,
        proposal,
        symbol=symbol,
        strategy=strategy_label,
    )
    print("\nJournal entry voorstel:\n" + journal_text)


def _submit_ib_order(
    session: ControlPanelSession, proposal: StrategyProposal, *, symbol: str | None = None
) -> None:
    ticker = symbol or str(session.symbol or "")
    if not ticker:
        print("❌ Geen symbool beschikbaar voor orderplaatsing.")
        return
    account = str(cfg.get("IB_ACCOUNT_ALIAS") or "") or None
    order_type = str(cfg.get("DEFAULT_ORDER_TYPE", "LMT"))
    tif = str(cfg.get("DEFAULT_TIME_IN_FORCE", "DAY"))
    try:
        instructions = prepare_order_instructions(
            proposal,
            symbol=ticker,
            account=account,
            order_type=order_type,
            tif=tif,
        )
    except Exception as exc:
        logger.exception("Ordervoorbereiding mislukt: %s", exc)
        print(f"❌ Kon order niet voorbereiden: {exc}")
        return

    export_dir = Path(cfg.get("EXPORT_DIR", "exports")) / datetime.now().strftime("%Y%m%d")
    log_path = OrderSubmissionService.dump_order_log(instructions, directory=export_dir)
    print(f"📝 Orderstructuur opgeslagen in: {log_path}")

    if cfg.get("IB_FETCH_ONLY", False):
        logger.info("fetch_only-modus actief; orders niet verzonden")
        return

    host = str(cfg.get("IB_HOST", "127.0.0.1"))
    paper_mode = bool(cfg.get("IB_PAPER_MODE", True))
    port_key = "IB_PORT" if paper_mode else "IB_LIVE_PORT"
    port = int(cfg.get(port_key, 7497 if paper_mode else 7496))
    client_id = int(cfg.get("IB_ORDER_CLIENT_ID", cfg.get("IB_CLIENT_ID", 100)))
    timeout = int(cfg.get("DOWNLOAD_TIMEOUT", 5))
    service = OrderSubmissionService()
    app = None
    try:
        app, order_ids = service.place_orders(
            instructions,
            host=host,
            port=port,
            client_id=client_id,
            timeout=timeout,
        )
    except Exception as exc:
        print(f"❌ Verzenden naar IB mislukt: {exc}")
        return
    finally:
        if app is not None:
            try:
                app.disconnect()
            except Exception:
                logger.debug("Probleem bij sluiten IB-verbinding", exc_info=True)

    print(f"✅ {len(order_ids)} order(s) als concept verstuurd naar IB (client {client_id}).")


def _save_trades(session: ControlPanelSession, trades: list[dict[str, object]]) -> None:
    symbol = str(session.symbol or "SYMB")
    strat = str(session.strategy or "strategy").replace(" ", "_")
    expiry = str(trades[0].get("expiry", "")) if trades else ""
    base = Path(cfg.get("EXPORT_DIR", "exports")) / datetime.now().strftime("%Y%m%d")
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
                if k in {"pos", "rom", "ev", "edge", "mid", "model", "delta", "margin"}:
                    try:
                        out[k] = f"{float(v):.2f}"
                    except Exception:
                        out[k] = ""
                else:
                    out[k] = v
            writer.writerow(out)
    print(f"✅ Trades opgeslagen in: {path.resolve()}")




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


def run_dataexporter(services: ControlPanelServices | None = None) -> None:
    """Menu for export and CSV validation utilities."""

    session = ControlPanelSession()
    if services is None:
        services = _create_services(session)

    menu = build_export_menu(
        session,
        services,
        run_module=run_module,
    )
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


def run_portfolio_menu(
    session: ControlPanelSession | None = None,
    services: ControlPanelServices | None = None,
) -> None:
    session = session or ControlPanelSession()
    services = services or _create_services(session)
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
    def print_factsheet(chosen: dict[str, object]) -> None:
        """Print key metrics for the selected recommendation."""

        factsheet = services.portfolio.build_factsheet(chosen)
        table_spec = build_factsheet_table(factsheet)
        print(tabulate(table_spec.rows, headers=table_spec.headers, tablefmt="github"))

    def show_market_info() -> None:
        symbols = [s.upper() for s in cfg.get("DEFAULT_SYMBOLS", [])]

        vix_value = None
        try:
            metrics = fetch_volatility_metrics(symbols[0] if symbols else "SPY")
            vix_value = metrics.get("vix")
        except Exception:
            vix_value = None
        if isinstance(vix_value, (int, float)):
            print(f"VIX {vix_value:.2f}")

        snapshot = services.market_snapshot.load_snapshot({"symbols": symbols})

        def _as_overview_row(data: object) -> list[object]:
            return [
                getattr(data, "symbol", None),
                getattr(data, "spot", None),
                getattr(data, "iv", None),
                getattr(data, "hv20", None),
                getattr(data, "hv30", None),
                getattr(data, "hv90", None),
                getattr(data, "hv252", None),
                getattr(data, "iv_rank", None),
                getattr(data, "iv_percentile", None),
                getattr(data, "term_m1_m2", None),
                getattr(data, "term_m1_m3", None),
                getattr(data, "skew", None),
                getattr(data, "next_earnings", None),
                getattr(data, "days_until_earnings", None),
            ]

        rows = [_as_overview_row(row) for row in snapshot.rows]

        recs, table_rows, meta = build_market_overview(rows)

        earnings_filtered = {}
        if isinstance(meta, dict):
            earnings_filtered = meta.get("earnings_filtered", {}) or {}
        if isinstance(earnings_filtered, dict) and earnings_filtered:
            total_hidden = sum(len(strategies) for strategies in earnings_filtered.values())
            detail_parts = []
            for symbol in sorted(earnings_filtered):
                strategies = ", ".join(earnings_filtered[symbol])
                detail_parts.append(f"{symbol}: {strategies}")
            detail_msg = "; ".join(detail_parts)
            print(
                f"ℹ️ {total_hidden} aanbevelingen verborgen vanwege earnings-filter"
                + (f" ({detail_msg})" if detail_msg else "")
            )

        if recs:
            portfolio_show_market_overview(tabulate, table_rows)

            while True:
                sel = prompt("Selectie (0 om terug, 999 voor scan): ")
                if sel == "999":
                    portfolio_run_market_scan(
                        session,
                        services,
                        recs,
                        tabulate_fn=tabulate,
                        prompt_fn=prompt,
                        show_proposal_details=_show_proposal_details,
                        refresh_spot_price_fn=refresh_spot_price,
                        load_spot_from_metrics_fn=load_spot_from_metrics,
                        load_latest_close_fn=_load_latest_close,
                        spot_from_chain_fn=spot_from_chain,
                    )
                    continue
                if sel in {"", "0"}:
                    break
                try:
                    idx = int(sel) - 1
                    chosen = recs[idx]
                except (ValueError, IndexError):
                    print("❌ Ongeldige keuze")
                    continue
                session.update_from_mapping(chosen)
                symbol_label = session.symbol or "—"
                strategy_label = session.strategy or "—"
                print(f"\n🎯 Gekozen strategie: {symbol_label} – {strategy_label}\n")
                print_factsheet(chosen)
                choose_chain_source()
                return
        else:
            print("⚠️ Geen aanbevelingen beschikbaar.")

    def show_informative_market_info() -> None:
        symbols = [s.upper() for s in cfg.get("DEFAULT_SYMBOLS", [])]

        vix_value = None
        try:
            metrics = fetch_volatility_metrics(symbols[0] if symbols else "SPY")
            vix_value = metrics.get("vix")
        except Exception:
            vix_value = None
        if isinstance(vix_value, (int, float)):
            print(f"VIX {vix_value:.2f}")

        snapshot = MARKET_SNAPSHOT_SERVICE.load_snapshot({"symbols": symbols})

        def fmt4(val: float | None) -> str:
            return f"{val:.4f}" if val is not None else ""

        def fmt2(val: float | None) -> str:
            return f"{val:.2f}" if val is not None else ""

        formatted_rows = []
        for row in snapshot.rows:
            formatted_rows.append(
                [
                    getattr(row, "symbol", None),
                    getattr(row, "spot", None),
                    fmt4(getattr(row, "iv", None)),
                    fmt4(getattr(row, "hv20", None)),
                    fmt4(getattr(row, "hv30", None)),
                    fmt4(getattr(row, "hv90", None)),
                    fmt4(getattr(row, "hv252", None)),
                    fmt2(getattr(row, "iv_rank", None)),
                    fmt2(getattr(row, "iv_percentile", None)),
                    getattr(row, "term_m1_m2", None),
                    getattr(row, "term_m1_m3", None),
                    getattr(row, "skew", None),
                    getattr(row, "next_earnings", None),
                ]
            )

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

    def _process_chain(path: Path) -> None:
        global SHOW_REASONS
        SHOW_REASONS = portfolio_process_chain(
            session,
            services,
            path,
            SHOW_REASONS,
            tabulate_fn=tabulate,
            prompt_fn=prompt,
            prompt_yes_no_fn=prompt_yes_no,
            show_proposal_details=_show_proposal_details,
            build_rejection_summary_fn=build_rejection_summary,
            save_trades_fn=_save_trades,
            refresh_spot_price_fn=refresh_spot_price,
            load_spot_from_metrics_fn=load_spot_from_metrics,
            load_latest_close_fn=_load_latest_close,
            spot_from_chain_fn=spot_from_chain,
            print_evaluation_overview_fn=_print_evaluation_overview,
        )

    def choose_chain_source() -> None:
        symbol = session.symbol
        if not symbol:
            print("⚠️ Geen strategie geselecteerd")
            return

        def use_ib() -> None:
            path = services.export.export_chain(str(symbol))
            if not path:
                print("⚠️ Geen chain gevonden")
                return
            _process_chain(path)

        def use_polygon() -> None:
            path = services.export.fetch_polygon_chain(str(symbol))
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
    menu.add(
        "Trademanagement (controleer exitcriteria)",
        lambda: run_module("tomic.cli.trade_management"),
    )
    menu.add("Toon marktinformatie", show_market_info)

    def _show_earnings_info() -> None:
        try:
            run_module("tomic.cli.earnings_info")
        except subprocess.CalledProcessError:
            print("❌ Earnings-informatie kon niet worden getoond")

    menu.add("Earnings-informatie", _show_earnings_info)
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
        host_default = cfg.get("IB_HOST")
        port_default = cfg.get("IB_PORT")
        host = prompt(f"Host ({host_default}): ", host_default)
        port_str = prompt(f"Poort ({port_default}): ")
        port = int(port_str) if port_str else port_default
        cfg.update({"IB_HOST": host, "IB_PORT": port})

    def change_symbols() -> None:
        print("Huidige symbols:", ", ".join(cfg.get("DEFAULT_SYMBOLS", [])))
        raw = prompt("Nieuw lijst (comma-sep): ")
        if raw:
            symbols = [s.strip().upper() for s in raw.split(",") if s.strip()]
            save_symbols(symbols)

    def change_rate() -> None:
        rate_default = cfg.get("INTEREST_RATE")
        rate_str = prompt(f"Rente ({rate_default}): ")
        if rate_str:
            try:
                rate = float(rate_str)
            except ValueError:
                print("❌ Ongeldige rente")
                return
            cfg.update({"INTEREST_RATE": rate})

    def change_path(key: str) -> None:
        current = cfg.get(key)
        value = prompt(f"{key} ({current}): ")
        if value:
            cfg.update({key: value})

    def change_int(key: str) -> None:
        current = cfg.get(key)
        val = prompt(f"{key} ({current}): ")
        if val:
            try:
                cfg.update({key: int(val)})
            except ValueError:
                print("❌ Ongeldige waarde")

    def change_float(key: str) -> None:
        current = cfg.get(key)
        val = prompt(f"{key} ({current}): ")
        if val:
            try:
                cfg.update({key: float(val)})
            except ValueError:
                print("❌ Ongeldige waarde")

    def change_str(key: str) -> None:
        current = cfg.get(key)
        val = prompt(f"{key} ({current}): ", current)
        if val:
            cfg.update({key: val})

    def change_bool(key: str) -> None:
        current = cfg.get(key)
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

    def run_rules_menu() -> None:
        path = prompt("Pad naar criteria.yaml (optioneel): ")
        sub = Menu("\U0001f4dc Criteria beheren")

        sub.add("Toon criteria", lambda: run_module("tomic.cli.rules", "show"))

        def _validate() -> None:
            if path:
                run_module("tomic.cli.rules", "validate", path)
            else:
                run_module("tomic.cli.rules", "validate")

        def _validate_reload() -> None:
            if path:
                run_module("tomic.cli.rules", "validate", path, "--reload")
            else:
                run_module("tomic.cli.rules", "validate", "--reload")

        sub.add("Valideer criteria.yaml", _validate)
        sub.add("Valideer & reload", _validate_reload)
        sub.add(
            "Reload zonder validatie", lambda: run_module("tomic.cli.rules", "reload")
        )
        sub.run()

    def run_strategy_criteria_menu() -> None:
        sub = Menu("\U0001f3af Strategie & Criteria")
        sub.add("Optie-strategie parameters", run_option_menu)
        sub.add("Criteria beheren", run_rules_menu)
        sub.run()

    menu = Menu("\u2699\ufe0f INSTELLINGEN & CONFIGURATIE")
    menu.add("Portfolio & Analyse", run_general_menu)
    menu.add("Verbinding & API", run_connection_menu)
    menu.add("Netwerk & Snelheid", run_network_menu)
    menu.add("Bestandslocaties", run_paths_menu)
    menu.add("Strategie & Criteria", run_strategy_criteria_menu)
    menu.add("Logging & Gedrag", run_logging_menu)
    menu.add("Toon volledige configuratie", show_config)
    menu.run()


def run_controlpanel(
    session: ControlPanelSession | None = None,
    services: ControlPanelServices | None = None,
) -> None:
    """Render the main control panel menu with injected dependencies."""

    session = session or ControlPanelSession()
    services = services or _create_services(session)

    menu = Menu("TOMIC CONTROL PANEL", exit_text="Stoppen")
    menu.add("Analyse & Strategie", lambda: run_portfolio_menu(session, services))
    menu.add("Data & Marktdata", lambda: run_dataexporter(services))
    menu.add("Trades & Journal", run_trade_management)
    menu.add("Risicotools & Synthetica", run_risk_tools)
    menu.add("Configuratie", run_settings_menu)
    menu.run()
    print("Tot ziens.")


def main(argv: list[str] | None = None) -> None:
    """Start the interactive control panel."""

    parser = argparse.ArgumentParser(description="TOMIC control panel")
    parser.add_argument(
        "--show-reasons",
        action="store_true",
        help="Toon selectie- en strategie-redenen",
    )
    args = parser.parse_args(argv or [])

    global SHOW_REASONS
    SHOW_REASONS = args.show_reasons

    session = ControlPanelSession()
    services = _create_services(session)
    run_controlpanel(session, services)


if __name__ == "__main__":
    main(sys.argv[1:])
