"""Control panel entrypoint orchestrating menu sections and context state."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, fields
from functools import partial
from pathlib import Path
from types import ModuleType
from typing import Iterable, Mapping

from tomic.cli.app_services import ControlPanelServices
from tomic.cli.common import Menu
from tomic.cli.controlpanel_session import ControlPanelSession
from .menu_config import MenuItem, MenuSection, build_menu
from . import portfolio


class _ControlPanelModule(ModuleType):
    """Module type that keeps ``SHOW_REASONS`` synchronized with submodules."""

    def __setattr__(self, name: str, value) -> None:  # type: ignore[override]
        if name == "SHOW_REASONS":
            portfolio.SHOW_REASONS = value
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
_show_proposal_details = portfolio._show_proposal_details
_process_chain_with_context = portfolio._process_chain_with_context


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
