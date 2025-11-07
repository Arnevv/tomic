"""Interactive command line interface for TOMIC utilities."""

import subprocess
import sys
from pathlib import Path
import inspect
from functools import partial
from typing import Any, Callable, Mapping, Sequence

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
from tomic.config import tws_option_chain_enabled
from tomic.core.portfolio import services as portfolio_services
from tomic.logutils import logger, setup_logging
from tomic.analysis.volatility_fetcher import fetch_volatility_metrics
from tomic.analysis.market_overview import build_market_overview
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
from tomic.exports import refresh_spot_price, load_spot_from_metrics, spot_from_chain
from tomic.services.strategy_pipeline import StrategyProposal
from tomic.strategy_candidates import generate_strategy_candidates
from tomic.strike_selector import StrikeSelector
from tomic.reporting import EvaluationSummary, format_reject_reasons
from tomic.reporting.rejections import (
    ExpiryBreakdown,
    _format_leg_summary as _reporting_format_leg_summary,
)
from tomic.formatting.portfolio_tables import build_factsheet_table
from tomic.formatting.table_builders import (
    proposal_earnings_table,
    proposal_legs_table,
    proposal_summary_table,
)

setup_logging(stdout=True)

pd = None  # pragma: no cover - placeholder for tests that monkeypatch pandas


def _default_symbols() -> list[str]:
    raw = cfg.get("DEFAULT_SYMBOLS", []) or []
    symbols: list[str] = []
    for value in raw:
        if not isinstance(value, (str, bytes)):
            continue
        cleaned = str(value).strip()
        if cleaned:
            symbols.append(cleaned.upper())
    return symbols


def _fetch_vix_value(symbols: Sequence[str]) -> float | None:
    base_symbol = symbols[0] if symbols else "SPY"
    try:
        metrics = fetch_volatility_metrics(base_symbol)
    except Exception:
        return None
    if isinstance(metrics, Mapping):
        value = metrics.get("vix")
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _snapshot_row_mapping(row: object) -> dict[str, Any]:
    return {
        "symbol": getattr(row, "symbol", None),
        "spot": getattr(row, "spot", None),
        "iv": getattr(row, "iv", None),
        "hv20": getattr(row, "hv20", None),
        "hv30": getattr(row, "hv30", None),
        "hv90": getattr(row, "hv90", None),
        "hv252": getattr(row, "hv252", None),
        "iv_rank": getattr(row, "iv_rank", None),
        "iv_percentile": getattr(row, "iv_percentile", None),
        "term_m1_m2": getattr(row, "term_m1_m2", None),
        "term_m1_m3": getattr(row, "term_m1_m3", None),
        "skew": getattr(row, "skew", None),
        "next_earnings": getattr(row, "next_earnings", None),
        "days_until_earnings": getattr(row, "days_until_earnings", None),
    }


def _overview_input(rows: Sequence[object]) -> list[list[Any]]:
    return [[mapping[key] for key in (
        "symbol",
        "spot",
        "iv",
        "hv20",
        "hv30",
        "hv90",
        "hv252",
        "iv_rank",
        "iv_percentile",
        "term_m1_m2",
        "term_m1_m3",
        "skew",
        "next_earnings",
        "days_until_earnings",
    )] for mapping in (_snapshot_row_mapping(row) for row in rows)]


def _format_snapshot_row(mapping: Mapping[str, Any]) -> list[str | Any]:
    def fmt(val: Any, digits: int) -> str:
        if isinstance(val, (int, float)):
            return f"{val:.{digits}f}"
        return ""

    return [
        mapping.get("symbol"),
        mapping.get("spot"),
        fmt(mapping.get("iv"), 4),
        fmt(mapping.get("hv20"), 4),
        fmt(mapping.get("hv30"), 4),
        fmt(mapping.get("hv90"), 4),
        fmt(mapping.get("hv252"), 4),
        fmt(mapping.get("iv_rank"), 2),
        fmt(mapping.get("iv_percentile"), 2),
        mapping.get("term_m1_m2"),
        mapping.get("term_m1_m3"),
        mapping.get("skew"),
        mapping.get("next_earnings"),
    ]


def _build_overview(rows: Sequence[list[Any]]) -> tuple[list[Mapping[str, Any]], list[list[str]], Mapping[str, Any]]:
    try:
        from tomic.cli import controlpanel as controlpanel_module  # type: ignore

        override = getattr(controlpanel_module, "build_market_overview", None)
    except Exception:
        override = None
    fn = override if callable(override) else build_market_overview
    return fn(rows)


_TWS_DISABLED_MESSAGE = (
    "TWS option-chain fetch is uitgeschakeld. Gebruik Polygon-marktdata."
)


def _notify_tws_disabled() -> None:
    logger.info("TWS option-chain fetch attempted while disabled")
    print(_TWS_DISABLED_MESSAGE)


def _handle_market_selection(
    selection: str,
    recs: Sequence[Mapping[str, Any]],
    *,
    tws_enabled: bool,
) -> tuple[str, Mapping[str, Any] | None]:
    if selection == "998":
        if not tws_enabled:
            return "tws_disabled", None
        return "refresh", None
    if selection == "999":
        return "scan", None
    if selection in {"", "0"}:
        return "exit", None
    try:
        idx = int(selection) - 1
        chosen = recs[idx]
    except (ValueError, IndexError):
        print("❌ Ongeldige keuze")
        return "retry", None
    return "choose", chosen


def _resolve_snapshot_service(services: ControlPanelServices):
    return MARKET_SNAPSHOT_SERVICE or services.market_snapshot


def _load_snapshot(
    services: ControlPanelServices,
    symbols: Sequence[str],
) -> Any:
    service = _resolve_snapshot_service(services)
    return service.load_snapshot({"symbols": list(symbols)})


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
    return portfolio_services.capture_strategy_generation(
        session,
        generate_strategy_candidates,
        *args,
        **kwargs,
    )


def _create_services(session: ControlPanelSession) -> ControlPanelServices:
    return create_controlpanel_services(
        strike_selector_factory=_strike_selector_factory,
        strategy_generator=lambda *args, **kwargs: _generate_with_capture(
            session, *args, **kwargs
        ),
    )


SHOW_REASONS = False


def _get_show_reasons(session: ControlPanelSession) -> bool:
    synced = getattr(session, "_show_reasons_synced", False)
    current = bool(getattr(session, "show_reasons", SHOW_REASONS))
    if not synced and current != SHOW_REASONS:
        return _set_show_reasons(session, SHOW_REASONS)
    return current


def _set_show_reasons(session: ControlPanelSession, value: bool) -> bool:
    session.show_reasons = bool(value)
    setattr(session, "_show_reasons_synced", True)
    globals()["SHOW_REASONS"] = session.show_reasons
    return session.show_reasons


def _show_proposal_details(
    session: ControlPanelSession, proposal: StrategyProposal
) -> None:
    base_symbol = (
        str(session.symbol or proposal.legs[0].get("symbol", ""))
        if proposal.legs
        else str(session.symbol or "")
    )
    symbol = base_symbol or None
    fetch_only_mode = bool(cfg.get("IB_FETCH_ONLY", False))
    refresh_result = None
    fetch_attempted = False

    def _attempt_ib_refresh() -> bool:
        nonlocal proposal, refresh_result, fetch_attempted
        try:
            refresh_result = portfolio_services.refresh_proposal_from_ib(
                proposal,
                symbol=symbol,
                spot_price=session.spot_price,
            )
        except Exception as exc:
            print(f"❌ Marktdata ophalen mislukt: {exc}")
            return False
        proposal = refresh_result.proposal
        fetch_attempted = True
        return True

    if fetch_only_mode or prompt_yes_no("Haal orderinformatie van IB op?", True):
        _attempt_ib_refresh()

    presentation = None
    vm = None

    while True:
        presentation = portfolio_services.build_proposal_presentation(
            session,
            proposal,
            refresh_result=refresh_result,
        )
        vm = presentation.viewmodel

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

        missing_bidask = fetch_attempted and any(
            leg.bid is None or leg.ask is None for leg in vm.legs
        )
        if missing_bidask:
            if prompt_yes_no("Bid/ask data niet compleet, retry uitvoeren?", False):
                if _attempt_ib_refresh():
                    print()
                    continue

        if presentation.acceptance_failed:
            print("❌ Acceptatiecriteria niet gehaald na IB-refresh.")
            for message in portfolio_services.rejection_messages(vm):
                print(f"  - {message}")

        if presentation.has_missing_edge and not cfg.get("ALLOW_INCOMPLETE_METRICS", False):
            if not prompt_yes_no(
                "⚠️ Deze strategie bevat onvolledige edge-informatie. Toch accepteren?",
                False,
            ):
                return

        break

    if prompt_yes_no("Voorstel opslaan naar CSV?", False):
        path = portfolio_services.export_proposal_to_csv(session, presentation.proposal)
        print(f"✅ Voorstel opgeslagen in: {path.resolve()}")
    if prompt_yes_no("Voorstel opslaan naar JSON?", False):
        path = portfolio_services.export_proposal_to_json(session, presentation.proposal)
        print(f"✅ Voorstel opgeslagen in: {path.resolve()}")

    can_send_order = not presentation.acceptance_failed and not presentation.fetch_only_mode
    order_symbol = presentation.symbol or symbol or str(session.symbol or "")
    if can_send_order and prompt_yes_no("Order naar IB sturen?", False):
        _submit_ib_order(session, presentation.proposal, symbol=order_symbol)
    elif presentation.fetch_only_mode:
        print("ℹ️ fetch_only modus actief – orders worden niet verzonden.")

    print("\nJournal entry voorstel:\n" + presentation.journal_text)


def _submit_ib_order(
    session: ControlPanelSession, proposal: StrategyProposal, *, symbol: str | None = None
) -> None:
    ticker = (symbol or str(session.symbol or "")).strip()
    if not ticker:
        print("❌ Geen symbool beschikbaar voor orderplaatsing.")
        return
    try:
        result = portfolio_services.submit_order(proposal, symbol=ticker)
    except portfolio_services.OrderSubmissionError as exc:
        print(f"❌ Kon order niet versturen: {exc}")
        return

    print(f"📝 Orderstructuur opgeslagen in: {result.log_path}")
    if result.fetch_only:
        print("ℹ️ fetch_only modus actief – orders worden niet verzonden.")
    else:
        count = len(result.order_ids)
        print(
            f"✅ {count} order(s) als concept verstuurd naar IB (client {result.client_id})."
        )


def _save_trades(session: ControlPanelSession, trades: list[dict[str, object]]) -> None:
    try:
        path = portfolio_services.save_trades(session, trades)
    except ValueError as exc:
        print(f"❌ {exc}")
        return
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
            str(portfolio_services.POSITIONS_FILE),
            str(portfolio_services.ACCOUNT_INFO_FILE),
            f"--view={view}",
        )
        run_module("tomic.analysis.performance_analyzer")
    except subprocess.CalledProcessError:
        print("❌ Dashboard kon niet worden gestart")


def show_saved_portfolio(session: ControlPanelSession, services: ControlPanelServices) -> None:
    if not (
        portfolio_services.POSITIONS_FILE.exists()
        and portfolio_services.ACCOUNT_INFO_FILE.exists()
    ):
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
            str(portfolio_services.POSITIONS_FILE),
            str(portfolio_services.ACCOUNT_INFO_FILE),
            f"--view={view}",
        )
        run_module("tomic.analysis.performance_analyzer")
    except subprocess.CalledProcessError:
        print("❌ Dashboard kon niet worden gestart")


def show_saved_greeks(session: ControlPanelSession, services: ControlPanelServices) -> None:
    if not portfolio_services.POSITIONS_FILE.exists():
        print("⚠️ Geen opgeslagen portfolio gevonden. Kies optie 1 om te verversen.")
        return
    try:
        run_module(
            "tomic.cli.portfolio_greeks",
            str(portfolio_services.POSITIONS_FILE),
        )
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
    symbols = _default_symbols()

    vix_value = _fetch_vix_value(symbols)
    if vix_value is not None:
        print(f"VIX {vix_value:.2f}")

    snapshot = _load_snapshot(services, symbols)
    rows = _overview_input(snapshot.rows)

    recs, table_rows, meta = _build_overview(rows)

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

    print("\n📋 Volatility Snapshot Aanbevelingen")
    portfolio_show_market_overview(tabulate, table_rows)

    selection_help_lines = [
        "\nSelectie maken:",
        "[nummer]  → Details voor één rij",
        "999       → Nieuwe Polygon-scan",
        "0         → Terug naar hoofdmenu",
    ]
    if tws_option_chain_enabled():
        selection_help_lines.insert(2, "998       → (niet beschikbaar) TWS-data")
    selection_help = "\n".join(selection_help_lines)
    tws_enabled = False
    print(selection_help)

    while True:
        sel = prompt("Keuze: ")
        action, chosen = _handle_market_selection(sel, recs, tws_enabled=tws_enabled)
        if action == "refresh":
            portfolio_run_market_scan(
                session,
                services,
                recs,
                tabulate_fn=tabulate,
                prompt_fn=prompt,
                prompt_yes_no_fn=prompt_yes_no,
                show_proposal_details=_show_proposal_details,
                refresh_spot_price_fn=refresh_spot_price,
                load_spot_from_metrics_fn=load_spot_from_metrics,
                load_latest_close_fn=portfolio_services.load_latest_close,
                spot_from_chain_fn=spot_from_chain,
                refresh_only=True,
            )
            portfolio_show_market_overview(tabulate, table_rows)
            print(selection_help)
            continue
        if action == "scan":
            portfolio_run_market_scan(
                session,
                services,
                recs,
                tabulate_fn=tabulate,
                prompt_fn=prompt,
                prompt_yes_no_fn=prompt_yes_no,
                show_proposal_details=_show_proposal_details,
                refresh_spot_price_fn=refresh_spot_price,
                load_spot_from_metrics_fn=load_spot_from_metrics,
                load_latest_close_fn=portfolio_services.load_latest_close,
                spot_from_chain_fn=spot_from_chain,
            )
            portfolio_show_market_overview(tabulate, table_rows)
            print(selection_help)
            continue
        if action == "tws_disabled":
            _notify_tws_disabled()
            continue
        if action == "exit":
            break
        if action != "choose" or chosen is None:
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
    symbols = _default_symbols()

    vix_value = _fetch_vix_value(symbols)
    if vix_value is not None:
        print(f"VIX {vix_value:.2f}")

    snapshot = _load_snapshot(services, symbols)
    formatted_rows = [
        _format_snapshot_row(_snapshot_row_mapping(row)) for row in snapshot.rows
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


def _process_chain_with_context(
    session: ControlPanelSession,
    services: ControlPanelServices,
    path: Path,
    show_reasons: bool,
) -> bool:
    _set_show_reasons(session, show_reasons)
    result = portfolio_process_chain(
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
        load_latest_close_fn=portfolio_services.load_latest_close,
        spot_from_chain_fn=spot_from_chain,
        print_evaluation_overview_fn=_print_evaluation_overview,
    )
    return _set_show_reasons(session, result)


def _run_chain_source(
    session: ControlPanelSession,
    services: ControlPanelServices,
    *,
    source: str | None,
    require_symbol: bool,
    loader: Callable[..., Path | str | None],
    missing_message: str | None,
) -> None:
    symbol_value = session.symbol
    if require_symbol and not symbol_value:
        print("⚠️ Geen strategie geselecteerd")
        return

    symbol_arg = str(symbol_value) if symbol_value else None
    if source:
        session.chain_source = source

    try:
        path_candidate = (
            loader(symbol_arg) if require_symbol else loader()
        )
    except TypeError:
        path_candidate = loader()

    if not path_candidate:
        if missing_message:
            print(missing_message)
        return

    _process_chain_with_context(
        session,
        services,
        Path(path_candidate),
        _get_show_reasons(session),
    )


def _process_exported_chain(session: ControlPanelSession, services: ControlPanelServices) -> None:
    _notify_tws_disabled()


def _process_polygon_chain(session: ControlPanelSession, services: ControlPanelServices) -> None:
    _run_chain_source(
        session,
        services,
        source="polygon",
        require_symbol=True,
        loader=lambda sym: services.export.fetch_polygon_chain(str(sym)),
        missing_message="⚠️ Geen polygon chain gevonden",
    )


def _process_manual_chain(session: ControlPanelSession, services: ControlPanelServices) -> None:
    def _prompt_path(_: str | None = None) -> Path | str | None:
        path_text = prompt("Pad naar CSV: ")
        return path_text or None

    _run_chain_source(
        session,
        services,
        source=None,
        require_symbol=False,
        loader=_prompt_path,
        missing_message=None,
    )


def choose_chain_source(session: ControlPanelSession, services: ControlPanelServices) -> None:
    menu = Menu("Chain ophalen")
    menu.add(
        "Download nieuwe chain via TWS (uitgeschakeld)",
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
    portfolio_services.record_portfolio_timestamp()


def load_portfolio_timestamp() -> str | None:
    """Return the ISO timestamp of the last portfolio update if available."""
    return portfolio_services.read_portfolio_timestamp()


def print_saved_portfolio_greeks() -> None:
    """Compute and display portfolio Greeks from saved positions."""
    greeks = portfolio_services.compute_saved_portfolio_greeks()
    if not greeks:
        return
    print("📐 Portfolio Greeks:")
    for key, val in greeks.items():
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
    menu.add("Toon marktinformatie (Polygon)", partial(show_market_info, session, services))
    menu.add(
        "Controleer exitcriteria en exit intent",
        partial(run_module, "tomic.cli.exit_flow"),
    )
    menu.add("Earnings-informatie", partial(show_earnings_info, session, services))
    menu.run()

def run_settings_menu(
    session: ControlPanelSession | None = None,
    services: ControlPanelServices | None = None,
) -> None:
    """Render the configuration menu using declarative metadata."""

    menu = build_settings_menu(SETTINGS_MENU, session, services)
    menu.run()
