"""Declarative menu configuration helpers for the control panel CLI."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Callable, Iterable, Sequence

from tomic.cli.app_services import ControlPanelServices
from tomic.cli.common import Menu
from tomic.cli.controlpanel_session import ControlPanelSession

Handler = Callable[[ControlPanelSession, ControlPanelServices], None]


@dataclass(frozen=True)
class MenuItem:
    """Declarative specification of a menu entry."""

    label: str
    handler: Handler


@dataclass(frozen=True)
class MenuSection:
    """Group of related menu entries."""

    title: str
    items: Sequence[MenuItem]


def build_menu(
    menu: Menu,
    sections: Iterable[MenuSection],
    *,
    session: ControlPanelSession,
    services: ControlPanelServices,
) -> None:
    """Populate ``menu`` with sections that open dedicated submenus."""

    for section in sections:
        menu.add(
            section.title,
            partial(_run_section_menu, section=section, session=session, services=services),
        )


def _run_section_menu(*, section: MenuSection, session: ControlPanelSession, services: ControlPanelServices) -> None:
    submenu = Menu(section.title)
    for item in section.items:
        submenu.add(item.label, partial(item.handler, session, services))
    submenu.run()
