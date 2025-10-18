"""Interactive command line interface for TOMIC utilities."""

import argparse
import subprocess
import sys
from datetime import datetime, date
import json
from pathlib import Path
import csv
import inspect
from functools import partial
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


from tomic import config as cfg
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
from tomic.cli.module_runner import run_module
from tomic.cli.settings.menu_config import SETTINGS_MENU
from tomic.cli.settings.handlers import build_settings_menu
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
from tomic.strike_selector import StrikeSelector
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
MARKET_SNAPSHOT_SERVICE = None


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


def start_trading_plan(session: ControlPanelSession, services: ControlPanelServices) -> None:
    run_module("tomic.cli.trading_plan")


def _run_trade_management_module(session: ControlPanelSession, services: ControlPanelServices) -> None:
    run_module("tomic.cli.trade_management")


def fetch_and_show_portfolio(session: ControlPanelSession, services: ControlPanelServices) -> None:
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


def show_saved_portfolio(session: ControlPanelSession, services: ControlPanelServices) -> None:
    if not (POSITIONS_FILE.exists() and ACCOUNT_INFO_FILE.exists()):
        print("⚠ Geen opgeslagen portfolio gevonden. Kies optie 1 om te verversen.")
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


def show_saved_greeks(session: ControlPanelSession, services: ControlPanelServices) -> None:
    if not POSITIONS_FILE.exists():
        print("⚠️ Geen opgeslagen portfolio gevonden. Kies optie 1 om te verversen.")
        return
    try:
        run_module("tomic.cli.portfolio_greeks", str(POSITIONS_FILE))
    except subprocess.CalledProcessError:
        print("❌ Greeks-overzicht kon niet worden getoond")


def _print_factsheet(
    session: ControlPanelSession,
    services: ControlPanelServices,
    chosen: dict[str, object],
) -> None:
    factsheet = services.portfolio.build_factsheet(chosen)
    table_spec = build_factsheet_table(factsheet)
    print(tabulate(table_spec.rows, headers=table_spec.headers, tablefmt="github"))


def show_market_info(session: ControlPanelSession, services: ControlPanelServices) -> None:
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

    earnings_filtered: dict[str, Sequence[str]] = {}
    if isinstance(meta, dict):
        earnings_filtered = meta.get("earnings_filtered", {}) or {}
    if earnings_filtered:
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

    if not recs:
        print("⚠️ Geen aanbevelingen beschikbaar.")
        return

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
        _print_factsheet(session, services, chosen)
        choose_chain_source(session, services)
        return


def show_informative_market_info(
    session: ControlPanelSession, services: ControlPanelServices
) -> None:
    symbols = [s.upper() for s in cfg.get("DEFAULT_SYMBOLS", [])]

    vix_value = None
    try:
        metrics = fetch_volatility_metrics(symbols[0] if symbols else "SPY")
        vix_value = metrics.get("vix")
    except Exception:
        vix_value = None
    if isinstance(vix_value, (int, float)):
        print(f"VIX {vix_value:.2f}")

    service = MARKET_SNAPSHOT_SERVICE or services.market_snapshot
    snapshot = service.load_snapshot({"symbols": symbols})

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


def _process_chain_with_context(
    session: ControlPanelSession,
    services: ControlPanelServices,
    path: Path,
    show_reasons: bool,
) -> bool:
    return portfolio_process_chain(
        session,
        services,
        path,
        show_reasons,
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


def _process_exported_chain(session: ControlPanelSession, services: ControlPanelServices) -> None:
    symbol = session.symbol
    if not symbol:
        print("⚠️ Geen strategie geselecteerd")
        return
    path = services.export.export_chain(str(symbol))
    if not path:
        print("⚠️ Geen chain gevonden")
        return
    global SHOW_REASONS
    SHOW_REASONS = _process_chain_with_context(session, services, path, SHOW_REASONS)


def _process_polygon_chain(session: ControlPanelSession, services: ControlPanelServices) -> None:
    symbol = session.symbol
    if not symbol:
        print("⚠️ Geen strategie geselecteerd")
        return
    path = services.export.fetch_polygon_chain(str(symbol))
    if not path:
        print("⚠️ Geen polygon chain gevonden")
        return
    global SHOW_REASONS
    SHOW_REASONS = _process_chain_with_context(session, services, path, SHOW_REASONS)


def _process_manual_chain(session: ControlPanelSession, services: ControlPanelServices) -> None:
    path_text = prompt("Pad naar CSV: ")
    if not path_text:
        return
    path = Path(path_text)
    global SHOW_REASONS
    SHOW_REASONS = _process_chain_with_context(session, services, path, SHOW_REASONS)


def choose_chain_source(session: ControlPanelSession, services: ControlPanelServices) -> None:
    menu = Menu("Chain ophalen")
    menu.add(
        "Download nieuwe chain via TWS",
        partial(_process_exported_chain, session, services),
    )
    menu.add(
        "Download nieuwe chain via Polygon",
        partial(_process_polygon_chain, session, services),
    )
    menu.add("CSV handmatig kiezen", partial(_process_manual_chain, session, services))
    menu.run()


def show_earnings_info(session: ControlPanelSession, services: ControlPanelServices) -> None:
    try:
        run_module("tomic.cli.earnings_info")
    except subprocess.CalledProcessError:
        print("❌ Earnings-informatie kon niet worden getoond")

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
        "Overzicht bekijken",
        partial(run_module, "tomic.journal.journal_inspector"),
    )
    menu.add(
        "Nieuwe trade aanmaken",
        partial(run_module, "tomic.journal.journal_updater"),
    )
    menu.add(
        "Trade aanpassen / snapshot toevoegen",
        partial(run_module, "tomic.journal.journal_inspector"),
    )
    menu.add(
        "Journal updaten met positie IDs",
        partial(run_module, "tomic.cli.link_positions"),
    )

    menu.add("Trade afsluiten", partial(run_module, "tomic.cli.close_trade"))
    menu.run()


def run_risk_tools() -> None:
    """Menu for risk analysis helpers."""

    menu = Menu("🚦 RISICO TOOLS & SYNTHETICA")
    menu.add("Entry checker", partial(run_module, "tomic.cli.entry_checker"))
    menu.add("Scenario-analyse", partial(run_module, "tomic.cli.portfolio_scenario"))
    menu.add("Event watcher", partial(run_module, "tomic.cli.event_watcher"))
    menu.add("Synthetics detector", partial(run_module, "tomic.cli.synthetics_detector"))
    menu.add("ATR Calculator", partial(run_module, "tomic.cli.atr_calculator"))
    menu.add(
        "Theoretical value calculator",
        partial(run_module, "tomic.cli.bs_calculator"),
    )
    menu.run()


def run_portfolio_menu(
    session: ControlPanelSession | None = None,
    services: ControlPanelServices | None = None,
) -> None:
    session = session or ControlPanelSession()
    services = services or _create_services(session)

    menu = Menu("📊 ANALYSE & STRATEGIE")
    menu.add("Trading Plan", partial(start_trading_plan, session, services))
    menu.add(
        "Portfolio ophalen en tonen",
        partial(fetch_and_show_portfolio, session, services),
    )
    menu.add(
        "Laatst opgehaalde portfolio tonen",
        partial(show_saved_portfolio, session, services),
    )
    menu.add(
        "Trademanagement (controleer exitcriteria)",
        partial(_run_trade_management_module, session, services),
    )
    menu.add("Toon marktinformatie", partial(show_market_info, session, services))
    menu.add("Earnings-informatie", partial(show_earnings_info, session, services))
    menu.run()

def run_settings_menu(
    session: ControlPanelSession | None = None,
    services: ControlPanelServices | None = None,
) -> None:
    """Render the configuration menu using declarative metadata."""

    menu = build_settings_menu(SETTINGS_MENU, session, services)
    menu.run()

