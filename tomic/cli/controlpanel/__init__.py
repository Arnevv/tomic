"""Control panel entrypoint orchestrating menu sections and context state."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, fields
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable, Mapping, Sequence

from tomic import config as _config
from tomic.analysis.market_overview import build_market_overview
from tomic.analysis.volatility_fetcher import (
    fetch_volatility_metrics as _fetch_volatility_metrics,
)
from tomic.cli import services as cli_services
from tomic.cli.app_services import ControlPanelServices
from tomic.cli.common import Menu, prompt, prompt_yes_no
from tomic.cli.controlpanel_session import ControlPanelSession
import tomic.cli.rejections.handlers as rejection_handlers
from tomic.cli.rejections.handlers import (
    build_rejection_summary,
    refresh_rejections,
    show_rejection_detail,
)
from tomic.cli.module_runner import run_module
from tomic.core.portfolio import services as portfolio_services
from tomic.exports import spot_from_chain
from tomic.integrations.polygon.client import PolygonClient
from tomic.logutils import capture_combo_evaluations, summarize_evaluations
from tomic.reporting import (
    EvaluationSummary,
    ReasonAggregator,
    format_reject_reasons,
)
from tomic.reporting.rejections import ExpiryBreakdown
from tomic.scripts.backfill_hv import run_backfill_hv
from tomic.services import build_proposal_from_entry, refresh_pipeline
from tomic.services.chain_processing import ChainPreparationConfig
from tomic.services.market_scan_service import MarketScanRequest, MarketScanService
from tomic.services.market_snapshot_service import MarketSnapshotService
from tomic.services.strategy_pipeline import RejectionSummary, StrategyProposal
from tomic.strategy.reasons import ReasonCategory, normalize_reason
from tomic.strategy_candidates import (
    generate_strategy_candidates as _generate_strategy_candidates,
)

from . import portfolio
from .menu_config import MenuItem, MenuSection, build_menu


class _ControlPanelModule(ModuleType):
    """Module type that keeps ``SHOW_REASONS`` synchronized with submodules."""

    def __getattr__(self, name: str):  # type: ignore[override]
        if hasattr(portfolio, name):
            return getattr(portfolio, name)
        raise AttributeError(name)

    def __setattr__(self, name: str, value) -> None:  # type: ignore[override]
        if name == "SHOW_REASONS":
            portfolio.SHOW_REASONS = value
        elif name == "MARKET_SNAPSHOT_SERVICE":
            portfolio.MARKET_SNAPSHOT_SERVICE = value
            if hasattr(_CONTEXT.services, "market_snapshot"):
                _CONTEXT.services.market_snapshot = value
        elif name == "fetch_volatility_metrics":
            setattr(portfolio, "fetch_volatility_metrics", value)
        elif name == "capture_combo_evaluations":
            globals()[name] = value
            setattr(portfolio_services, "capture_combo_evaluations", value)
        elif hasattr(portfolio, name):
            setattr(portfolio, name, value)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _ControlPanelModule  # type: ignore[misc]


@dataclass
class ControlPanelContext:
    """Runtime state shared between menu handlers."""

    session: ControlPanelSession
    services: ControlPanelServices


class SessionState(dict):
    """Dict-like view that stays in sync with the active session."""

    def __init__(self, context: ControlPanelContext) -> None:
        super().__init__()
        self._context = context
        self.sync_from_session()

    def sync_from_session(self) -> None:
        super().clear()
        for field in fields(ControlPanelSession):
            value = getattr(self._context.session, field.name)
            if isinstance(value, list):
                value = list(value)
            super().__setitem__(field.name, value)

    def __setitem__(self, key: str, value) -> None:  # type: ignore[override]
        super().__setitem__(key, value)
        if hasattr(self._context.session, key):
            setattr(self._context.session, key, value)

    def update(self, other: Iterable | None = None, **kwargs) -> None:  # type: ignore[override]
        if other:
            if isinstance(other, Mapping):
                items = other.items()
            else:
                items = dict(other).items()
            for key, value in items:
                self[key] = value
        for key, value in kwargs.items():
            self[key] = value

    def clear(self) -> None:  # type: ignore[override]
        self._context.session = ControlPanelSession()
        self._context.services = portfolio._create_services(self._context.session)
        self.sync_from_session()


def _create_context() -> ControlPanelContext:
    session = ControlPanelSession()
    services = portfolio._create_services(session)
    return ControlPanelContext(session=session, services=services)


_CONTEXT = _create_context()
SESSION_STATE = SessionState(_CONTEXT)
SHOW_REASONS = portfolio.SHOW_REASONS
services = cli_services

# Backwards compatibility for tests that patch the paths directly via the
# controlpanel module instead of ``portfolio_services``.
POSITIONS_FILE = portfolio_services.POSITIONS_FILE
fetch_volatility_metrics = _fetch_volatility_metrics
cfg = _config


class _PipelineAccessor:
    def __getattr__(self, name: str) -> Any:  # type: ignore[override]
        pipeline = _CONTEXT.services.get_pipeline()
        return getattr(pipeline, name)


PIPELINE = _PipelineAccessor()


def _sync_state() -> None:
    SESSION_STATE.sync_from_session()


def _open_portfolio_menu(session: ControlPanelSession, services: ControlPanelServices) -> None:
    portfolio.run_portfolio_menu(session, services)
    _sync_state()


def _refresh_show_reasons() -> None:
    global SHOW_REASONS
    SHOW_REASONS = portfolio.SHOW_REASONS


def _open_data_menu(session: ControlPanelSession, services: ControlPanelServices) -> None:
    portfolio.run_dataexporter(services)


def _open_trades_menu(session: ControlPanelSession, services: ControlPanelServices) -> None:
    portfolio.run_trade_management()


def _open_risk_menu(session: ControlPanelSession, services: ControlPanelServices) -> None:
    portfolio.run_risk_tools()


def _open_settings_menu(session: ControlPanelSession, services: ControlPanelServices) -> None:
    portfolio.run_settings_menu(session, services)
    _sync_state()


ROOT_SECTIONS: list[MenuSection] = [
    MenuSection(
        "Analyse & Strategie",
        [
            MenuItem("Analyse-menu openen", _open_portfolio_menu),
        ],
    ),
    MenuSection(
        "Data & Marktdata",
        [
            MenuItem("Data-exporteurs", _open_data_menu),
        ],
    ),
    MenuSection(
        "Trades & Journal",
        [
            MenuItem("Trades beheren", _open_trades_menu),
        ],
    ),
    MenuSection(
        "Risicotools & Synthetica",
        [
            MenuItem("Risicotools", _open_risk_menu),
        ],
    ),
    MenuSection(
        "Configuratie",
        [
            MenuItem("Instellingen", _open_settings_menu),
        ],
    ),
]


def run_controlpanel(
    session: ControlPanelSession | None = None,
    services: ControlPanelServices | None = None,
) -> None:
    """Render the root control panel menu built from declarative sections."""

    if session is None:
        session = _CONTEXT.session
    else:
        _CONTEXT.session = session
    if services is None:
        services = _CONTEXT.services
    else:
        _CONTEXT.services = services

    menu = Menu("TOMIC CONTROL PANEL", exit_text="Stoppen")
    build_menu(menu, ROOT_SECTIONS, session=session, services=services)
    menu.run()
    print("Tot ziens.")
    _sync_state()


def _process_chain(path: Path) -> None:
    global SHOW_REASONS
    SHOW_REASONS = portfolio._process_chain_with_context(
        _CONTEXT.session,
        _CONTEXT.services,
        path,
        SHOW_REASONS,
    )
    portfolio.SHOW_REASONS = SHOW_REASONS
    _sync_state()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="TOMIC control panel")
    parser.add_argument(
        "--show-reasons",
        action="store_true",
        help="Toon selectie- en strategie-redenen",
    )
    args = parser.parse_args(argv or [])

    global SHOW_REASONS
    SHOW_REASONS = bool(args.show_reasons)
    portfolio.SHOW_REASONS = SHOW_REASONS

    run_controlpanel()

def run_portfolio_menu(
    session: ControlPanelSession | None = None,
    services: ControlPanelServices | None = None,
) -> None:
    if session is None:
        session = _CONTEXT.session
    if services is None:
        services = _CONTEXT.services
    portfolio.run_portfolio_menu(session, services)
    _sync_state()


def run_settings_menu(
    session: ControlPanelSession | None = None,
    services: ControlPanelServices | None = None,
) -> None:
    portfolio.run_settings_menu(
        session or _CONTEXT.session,
        services or _CONTEXT.services,
    )
    _sync_state()


def _process_exported_chain(session: ControlPanelSession, services: ControlPanelServices) -> None:
    portfolio._process_exported_chain(session, services)
    _refresh_show_reasons()
    _sync_state()


def _process_polygon_chain(session: ControlPanelSession, services: ControlPanelServices) -> None:
    portfolio._process_polygon_chain(session, services)
    _refresh_show_reasons()
    _sync_state()


def _process_manual_chain(session: ControlPanelSession, services: ControlPanelServices) -> None:
    portfolio._process_manual_chain(session, services)
    _refresh_show_reasons()
    _sync_state()


_show_earnings_info = portfolio.show_earnings_info
_process_chain_with_context = portfolio._process_chain_with_context
_show_proposal_details = portfolio._show_proposal_details


def choose_chain_source(session: ControlPanelSession, services: ControlPanelServices) -> None:
    portfolio.choose_chain_source(session, services)
    _refresh_show_reasons()
    _sync_state()


def show_market_info(session: ControlPanelSession, services: ControlPanelServices) -> None:
    portfolio.show_market_info(session, services)
    _refresh_show_reasons()
    _sync_state()


def show_informative_market_info(
    session: ControlPanelSession, services: ControlPanelServices
) -> None:
    portfolio.show_informative_market_info(session, services)
    _refresh_show_reasons()
    _sync_state()


# Re-export portfolio helpers for compatibility
_format_leg_summary = portfolio._format_leg_summary
_format_reject_reasons = portfolio._format_reject_reasons
_show_proposal_details = portfolio._show_proposal_details
_submit_ib_order = portfolio._submit_ib_order
_save_trades = portfolio._save_trades
save_portfolio_timestamp = portfolio.save_portfolio_timestamp
load_portfolio_timestamp = portfolio.load_portfolio_timestamp
print_saved_portfolio_greeks = portfolio.print_saved_portfolio_greeks
run_dataexporter = portfolio.run_dataexporter
run_trade_management = portfolio.run_trade_management
run_risk_tools = portfolio.run_risk_tools
generate_strategy_candidates = _generate_strategy_candidates
_print_evaluation_overview = portfolio._print_evaluation_overview

MARKET_SNAPSHOT_SERVICE = MarketSnapshotService(cfg)
_CONTEXT.services.market_snapshot = MARKET_SNAPSHOT_SERVICE
fetch_volatility_metrics = _fetch_volatility_metrics
build_market_overview = build_market_overview
MarketSnapshotService = MarketSnapshotService
MarketScanService = MarketScanService
MarketScanRequest = MarketScanRequest
StrategyProposal = StrategyProposal
RejectionSummary = RejectionSummary
EvaluationSummary = EvaluationSummary
ExpiryBreakdown = ExpiryBreakdown
format_reject_reasons = format_reject_reasons
capture_combo_evaluations = capture_combo_evaluations
ChainPreparationConfig = ChainPreparationConfig
PolygonClient = PolygonClient
refresh_pipeline = refresh_pipeline
build_proposal_from_entry = build_proposal_from_entry
spot_from_chain = spot_from_chain
_spot_from_chain = spot_from_chain
normalize_reason = normalize_reason

_ORIGINAL_REFRESH_REJECTIONS = refresh_rejections
setattr(portfolio, "fetch_volatility_metrics", fetch_volatility_metrics)
setattr(portfolio, "MARKET_SNAPSHOT_SERVICE", MARKET_SNAPSHOT_SERVICE)
setattr(portfolio, "build_market_overview", build_market_overview)
setattr(portfolio, "MarketScanService", MarketScanService)


def _refresh_reject_entries(
    entries: Sequence[Mapping[str, Any]],
    *,
    session: ControlPanelSession | None = None,
    services: ControlPanelServices | None = None,
    config: Any | None = None,
    tabulate_fn: Any | None = None,
    prompt_fn: Any | None = None,
    **_: Any,
) -> None:
    table = tabulate_fn or getattr(portfolio, "tabulate", None)
    _ORIGINAL_REFRESH_REJECTIONS(
        session or _CONTEXT.session,
        services or _CONTEXT.services,
        entries,
        config=config or cfg,
        show_proposal_details=_show_proposal_details,
        tabulate_fn=table,
        prompt_fn=prompt_fn or prompt,
    )


def _print_reason_summary(summary: RejectionSummary | None) -> None:
    original = rejection_handlers.refresh_rejections

    def _proxy(
        session: ControlPanelSession,
        services: ControlPanelServices,
        entries: Sequence[Mapping[str, Any]],
        **kwargs: Any,
    ) -> None:
        _refresh_reject_entries(entries)

    rejection_handlers.refresh_rejections = _proxy
    try:
        build_rejection_summary(
            _CONTEXT.session,
            summary,
            services=_CONTEXT.services,
            config=cfg,
            show_reasons=SHOW_REASONS,
            tabulate_fn=getattr(portfolio, "tabulate", None),
            prompt_fn=prompt,
            prompt_yes_no_fn=prompt_yes_no,
            show_proposal_details=_show_proposal_details,
        )
    finally:
        rejection_handlers.refresh_rejections = original


def _export_proposal_json(proposal: StrategyProposal) -> Path:
    path = portfolio_services.export_proposal_to_json(_CONTEXT.session, proposal)
    _sync_state()
    return path


def _show_rejection_detail(entry: Mapping[str, Any]) -> None:
    show_rejection_detail(
        _CONTEXT.session,
        entry,
        tabulate_fn=getattr(portfolio, "tabulate", None),
        prompt_fn=prompt,
        show_proposal_details=_show_proposal_details,
    )


def _generate_with_capture(*args: Any, **kwargs: Any):
    return portfolio_services.capture_strategy_generation(
        _CONTEXT.session,
        generate_strategy_candidates,
        *args,
        **kwargs,
    )


portfolio_refresh_reject_entries = _refresh_reject_entries
portfolio_print_reason_summary = _print_reason_summary
portfolio_export_proposal_json = _export_proposal_json
portfolio_show_rejection_detail = _show_rejection_detail
portfolio_generate_with_capture = _generate_with_capture

