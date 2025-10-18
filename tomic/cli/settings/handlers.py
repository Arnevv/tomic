"""Handlers and builders for the interactive settings menu."""

from __future__ import annotations

import os
from typing import Callable, Dict, Mapping, Optional, TYPE_CHECKING

from tomic import config as cfg
from tomic.cli.common import Menu, prompt, prompt_yes_no
from tomic.cli.module_runner import run_module
from tomic.cli.settings.menu_config import FieldType, SettingAction, SettingField, SettingMenu
from tomic.config import save_symbols
from tomic.logutils import setup_logging
from tomic.api.ib_connection import connect_ib

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from tomic.cli.app_services import ControlPanelServices
    from tomic.cli.controlpanel_session import ControlPanelSession
else:  # pragma: no cover - runtime placeholders to avoid heavy imports
    ControlPanelServices = ControlPanelSession = object  # type: ignore


ActionHandler = Callable[
    [Optional["ControlPanelSession"], Optional["ControlPanelServices"]],
    None,
]


def _format_label(field: SettingField) -> str:
    return field.label or field.key


def handle_string(field: SettingField, *, prompt_func: Callable[..., str] = prompt) -> None:
    """Prompt for a string value and persist it to the config."""

    current = cfg.get(field.key, "")
    value = prompt_func(f"{_format_label(field)} ({current}): ", str(current) or None)
    if value:
        cfg.update({field.key: value})


def handle_path(field: SettingField, *, prompt_func: Callable[..., str] = prompt) -> None:
    """Prompt for a filesystem path and persist it when provided."""

    current = cfg.get(field.key, "")
    value = prompt_func(f"{_format_label(field)} ({current}): ")
    if value:
        cfg.update({field.key: value})


def handle_int(field: SettingField, *, prompt_func: Callable[..., str] = prompt) -> None:
    """Prompt for an integer and update configuration when valid."""

    current = cfg.get(field.key, 0)
    raw = prompt_func(f"{_format_label(field)} ({current}): ")
    if not raw:
        return
    try:
        value = int(raw)
    except ValueError:
        print("❌ Ongeldige waarde")
        return
    cfg.update({field.key: value})


def handle_float(field: SettingField, *, prompt_func: Callable[..., str] = prompt) -> None:
    """Prompt for a floating point value and update configuration."""

    current = cfg.get(field.key, 0.0)
    raw = prompt_func(f"{_format_label(field)} ({current}): ")
    if not raw:
        return
    try:
        value = float(raw)
    except ValueError:
        print("❌ Ongeldige waarde")
        return
    cfg.update({field.key: value})


def handle_bool(
    field: SettingField,
    *,
    prompt_yes_no_func: Callable[[str, bool], bool] = prompt_yes_no,
) -> None:
    """Toggle a boolean configuration value based on user confirmation."""

    current = bool(cfg.get(field.key, False))
    value = prompt_yes_no_func(f"{_format_label(field)}?", current)
    cfg.update({field.key: value})


def handle_log_level(field: SettingField) -> None:
    """Set the configured logging level and refresh loggers."""

    target = field.log_level or "INFO"
    cfg.update({field.key: target})
    os.environ["TOMIC_LOG_LEVEL"] = target
    setup_logging()


_FIELD_HANDLERS: Mapping[FieldType, Callable[[SettingField], None]] = {
    "str": handle_string,
    "path": handle_path,
    "int": handle_int,
    "float": handle_float,
    "bool": handle_bool,
    "log_level": handle_log_level,
}


def change_host(session: "ControlPanelSession" | None, services: "ControlPanelServices" | None) -> None:
    """Prompt for IB host/port combination."""

    host_default = cfg.get("IB_HOST", "127.0.0.1")
    port_default = cfg.get("IB_PORT", 7497)
    host = prompt(f"Host ({host_default}): ", str(host_default))
    port_raw = prompt(f"Poort ({port_default}): ")
    port = port_default
    if port_raw:
        try:
            port = int(port_raw)
        except ValueError:
            print("❌ Ongeldige waarde")
            return
    cfg.update({"IB_HOST": host, "IB_PORT": port})


def change_symbols(session: "ControlPanelSession" | None, services: "ControlPanelServices" | None) -> None:
    """Update the default symbols list from user input."""

    current = cfg.get("DEFAULT_SYMBOLS", [])
    if current:
        print("Huidige symbols:", ", ".join(current))
    raw = prompt("Nieuw lijst (comma-sep): ")
    if not raw:
        return
    symbols = [s.strip().upper() for s in raw.split(",") if s.strip()]
    save_symbols(symbols)


def show_config(session: "ControlPanelSession" | None, services: "ControlPanelServices" | None) -> None:
    """Print the current configuration values."""

    asdict = (
        cfg.CONFIG.model_dump
        if hasattr(cfg.CONFIG, "model_dump")
        else cfg.CONFIG.dict  # type: ignore[attr-defined]
    )
    for key, value in asdict().items():
        print(f"{key}: {value}")


def check_ib_connection(
    session: "ControlPanelSession" | None,
    services: "ControlPanelServices" | None,
) -> None:
    """Test whether the IB API is reachable."""

    try:
        app = connect_ib()
        app.disconnect()
        print("✅ Verbinding met TWS beschikbaar")
    except Exception:
        print("❌ Geen verbinding met TWS")


def print_api_version(
    session: "ControlPanelSession" | None,
    services: "ControlPanelServices" | None,
) -> None:
    """Connect to TWS and display the server version information."""

    app = None
    try:
        app = connect_ib()
        print(f"Server versie: {app.serverVersion()}")
        print(f"Verbindingstijd: {app.twsConnectionTime()}")
    except Exception:
        print("❌ Geen verbinding met TWS")
    finally:
        if app is not None:
            try:
                app.disconnect()
            except Exception:
                pass


def show_open_settings(
    session: "ControlPanelSession" | None,
    services: "ControlPanelServices" | None,
) -> None:
    """Display current market-open configuration."""

    print("Huidige reqMktData instellingen:")
    print(f"MKT_GENERIC_TICKS: {cfg.get('MKT_GENERIC_TICKS', '100,101,106')}")
    print(f"UNDERLYING_PRIMARY_EXCHANGE: {cfg.get('UNDERLYING_PRIMARY_EXCHANGE', '')}")
    print(f"OPTIONS_PRIMARY_EXCHANGE: {cfg.get('OPTIONS_PRIMARY_EXCHANGE', '')}")


def show_closed_settings(
    session: "ControlPanelSession" | None,
    services: "ControlPanelServices" | None,
) -> None:
    """Display current market-closed configuration."""

    print("Huidige reqHistoricalData instellingen:")
    print(
        f"USE_HISTORICAL_IV_WHEN_CLOSED: {cfg.get('USE_HISTORICAL_IV_WHEN_CLOSED', True)}"
    )
    print(f"HIST_DURATION: {cfg.get('HIST_DURATION', '1 D')}")
    print(f"HIST_BARSIZE: {cfg.get('HIST_BARSIZE', '1 day')}")
    print(f"HIST_WHAT: {cfg.get('HIST_WHAT', 'TRADES')}")
    print(f"UNDERLYING_PRIMARY_EXCHANGE: {cfg.get('UNDERLYING_PRIMARY_EXCHANGE', '')}")
    print(f"OPTIONS_PRIMARY_EXCHANGE: {cfg.get('OPTIONS_PRIMARY_EXCHANGE', '')}")


def run_rules_menu(
    session: "ControlPanelSession" | None,
    services: "ControlPanelServices" | None,
) -> None:
    """Interactive submenu for criteria management."""

    path = prompt("Pad naar criteria.yaml (optioneel): ")
    menu = Menu("📜 Criteria beheren")

    menu.add("Toon criteria", lambda: run_module("tomic.cli.rules", "show"))

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

    menu.add("Valideer criteria.yaml", _validate)
    menu.add("Valideer & reload", _validate_reload)
    menu.add(
        "Reload zonder validatie", lambda: run_module("tomic.cli.rules", "reload")
    )
    menu.run()


_ACTION_HANDLERS: Dict[str, ActionHandler] = {
    "change_host": change_host,
    "change_symbols": change_symbols,
    "check_ib_connection": check_ib_connection,
    "print_api_version": print_api_version,
    "show_config": show_config,
    "run_rules_menu": run_rules_menu,
    "show_open_settings": show_open_settings,
    "show_closed_settings": show_closed_settings,
}


def _resolve_action(action: SettingAction) -> ActionHandler:
    try:
        return _ACTION_HANDLERS[action.action_id]
    except KeyError as exc:  # pragma: no cover - defensive programming
        raise KeyError(f"Onbekende actie: {action.action_id}") from exc


def _run_submenu(
    menu_def: SettingMenu,
    session: "ControlPanelSession" | None,
    services: "ControlPanelServices" | None,
) -> None:
    if menu_def.pre_run_action:
        action = _resolve_action(SettingAction(menu_def.pre_run_action, ""))
        action(session, services)
    submenu = _build_menu(menu_def, session, services)
    submenu.run()


def _build_menu(
    menu_def: SettingMenu,
    session: "ControlPanelSession" | None,
    services: "ControlPanelServices" | None,
) -> Menu:
    menu = Menu(menu_def.title)
    for item in menu_def.items:
        if isinstance(item, SettingField):
            handler = _FIELD_HANDLERS[item.field_type]
            menu.add(
                _format_label(item),
                lambda field=item, func=handler: func(field),
            )
        elif isinstance(item, SettingAction):
            action = _resolve_action(item)
            menu.add(item.label, lambda action=action: action(session, services))
        elif isinstance(item, SettingMenu):
            menu.add(
                item.label,
                lambda submenu=item: _run_submenu(submenu, session, services),
            )
    return menu


def build_settings_menu(
    fields: SettingMenu,
    session: "ControlPanelSession" | None,
    services: "ControlPanelServices" | None,
) -> Menu:
    """Build the settings menu tree from declarative metadata."""

    return _build_menu(fields, session, services)
