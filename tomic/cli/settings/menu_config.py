"""Declarative configuration for the control panel settings menu."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Tuple, Union

FieldType = Literal["str", "int", "float", "bool", "path", "log_level"]


@dataclass(frozen=True)
class SettingField:
    """Configuration field metadata used to build interactive menus."""

    key: str
    field_type: FieldType
    label: str | None = None
    log_level: str | None = None


@dataclass(frozen=True)
class SettingAction:
    """Named action that resolves to a callable handler at runtime."""

    action_id: str
    label: str


@dataclass(frozen=True)
class SettingMenu:
    """Nested menu definition for settings sections."""

    label: str
    title: str
    items: Tuple["SettingItem", ...]
    pre_run_action: str | None = None


SettingItem = Union[SettingField, SettingAction, SettingMenu]


SETTINGS_MENU = SettingMenu(
    label="⚙️ INSTELLINGEN & CONFIGURATIE",
    title="⚙️ INSTELLINGEN & CONFIGURATIE",
    items=(
        SettingMenu(
            label="📈 Portfolio & Analyse",
            title="📈 Portfolio & Analyse",
            items=(
                SettingAction(
                    action_id="change_symbols",
                    label="Pas default symbols aan",
                ),
                SettingField(
                    key="INTEREST_RATE",
                    field_type="float",
                    label="Pas interest rate aan",
                ),
                SettingField(
                    key="USE_HISTORICAL_IV_WHEN_CLOSED",
                    field_type="bool",
                ),
                SettingField(
                    key="INCLUDE_GREEKS_ONLY_IF_MARKET_OPEN",
                    field_type="bool",
                ),
            ),
        ),
        SettingMenu(
            label="🔌 Verbinding & API",
            title="🔌 Verbinding & API – TWS instellingen en tests",
            items=(
                SettingAction(
                    action_id="change_host",
                    label="Pas IB host/poort aan",
                ),
                SettingField(
                    key="IB_CLIENT_ID",
                    field_type="int",
                    label="Wijzig client ID",
                ),
                SettingAction(
                    action_id="check_ib_connection",
                    label="Test TWS-verbinding",
                ),
                SettingAction(
                    action_id="print_api_version",
                    label="Haal TWS API-versie op",
                ),
            ),
        ),
        SettingMenu(
            label="🌐 Netwerk & Snelheid",
            title="🌐 Netwerk & Snelheid",
            items=(
                SettingField(
                    key="CONTRACT_DETAILS_TIMEOUT",
                    field_type="int",
                ),
                SettingField(
                    key="CONTRACT_DETAILS_RETRIES",
                    field_type="int",
                ),
                SettingField(
                    key="DOWNLOAD_TIMEOUT",
                    field_type="int",
                ),
                SettingField(
                    key="DOWNLOAD_RETRIES",
                    field_type="int",
                ),
                SettingField(
                    key="MAX_CONCURRENT_REQUESTS",
                    field_type="int",
                ),
                SettingField(
                    key="BID_ASK_TIMEOUT",
                    field_type="int",
                ),
                SettingField(
                    key="MARKET_DATA_TIMEOUT",
                    field_type="int",
                ),
                SettingField(
                    key="OPTION_DATA_RETRIES",
                    field_type="int",
                ),
                SettingField(
                    key="OPTION_RETRY_WAIT",
                    field_type="int",
                ),
            ),
        ),
        SettingMenu(
            label="📁 Bestandslocaties",
            title="📁 Bestandslocaties",
            items=(
                SettingField(
                    key="ACCOUNT_INFO_FILE",
                    field_type="path",
                ),
                SettingField(
                    key="JOURNAL_FILE",
                    field_type="path",
                ),
                SettingField(
                    key="POSITIONS_FILE",
                    field_type="path",
                ),
                SettingField(
                    key="PORTFOLIO_META_FILE",
                    field_type="path",
                ),
                SettingField(
                    key="VOLATILITY_DB",
                    field_type="path",
                ),
                SettingField(
                    key="EXPORT_DIR",
                    field_type="path",
                ),
            ),
        ),
        SettingMenu(
            label="🎯 Strategie & Criteria",
            title="🎯 Strategie & Criteria",
            items=(
                SettingMenu(
                    label="📝 Optie-strategie parameters",
                    title="📝 Optie-strategie parameters",
                    items=(
                        SettingField(
                            key="STRIKE_RANGE",
                            field_type="int",
                        ),
                        SettingField(
                            key="FIRST_EXPIRY_MIN_DTE",
                            field_type="int",
                        ),
                        SettingField(
                            key="DELTA_MIN",
                            field_type="float",
                        ),
                        SettingField(
                            key="DELTA_MAX",
                            field_type="float",
                        ),
                        SettingField(
                            key="AMOUNT_REGULARS",
                            field_type="int",
                        ),
                        SettingField(
                            key="AMOUNT_WEEKLIES",
                            field_type="int",
                        ),
                        SettingField(
                            key="UNDERLYING_EXCHANGE",
                            field_type="str",
                        ),
                        SettingField(
                            key="UNDERLYING_PRIMARY_EXCHANGE",
                            field_type="str",
                        ),
                        SettingField(
                            key="OPTIONS_EXCHANGE",
                            field_type="str",
                        ),
                        SettingField(
                            key="OPTIONS_PRIMARY_EXCHANGE",
                            field_type="str",
                        ),
                        SettingMenu(
                            label="Markt open – reqMktData",
                            title="Markt open – reqMktData",
                            pre_run_action="show_open_settings",
                            items=(
                                SettingField(
                                    key="MKT_GENERIC_TICKS",
                                    field_type="str",
                                ),
                                SettingField(
                                    key="UNDERLYING_PRIMARY_EXCHANGE",
                                    field_type="str",
                                ),
                                SettingField(
                                    key="OPTIONS_PRIMARY_EXCHANGE",
                                    field_type="str",
                                ),
                            ),
                        ),
                        SettingMenu(
                            label="Markt dicht – reqHistoricalData",
                            title="Markt dicht – reqHistoricalData",
                            pre_run_action="show_closed_settings",
                            items=(
                                SettingField(
                                    key="USE_HISTORICAL_IV_WHEN_CLOSED",
                                    field_type="bool",
                                ),
                                SettingField(
                                    key="HIST_DURATION",
                                    field_type="str",
                                ),
                                SettingField(
                                    key="HIST_BARSIZE",
                                    field_type="str",
                                ),
                                SettingField(
                                    key="HIST_WHAT",
                                    field_type="str",
                                ),
                                SettingField(
                                    key="UNDERLYING_PRIMARY_EXCHANGE",
                                    field_type="str",
                                ),
                                SettingField(
                                    key="OPTIONS_PRIMARY_EXCHANGE",
                                    field_type="str",
                                ),
                            ),
                        ),
                    ),
                ),
                SettingAction(
                    action_id="run_rules_menu",
                    label="Criteria beheren",
                ),
            ),
        ),
        SettingMenu(
            label="🪵 Logging & Gedrag",
            title="🪵 Logging & Gedrag",
            items=(
                SettingField(
                    key="LOG_LEVEL",
                    field_type="log_level",
                    label="Stel logniveau in op INFO",
                    log_level="INFO",
                ),
                SettingField(
                    key="LOG_LEVEL",
                    field_type="log_level",
                    label="Stel logniveau in op DEBUG",
                    log_level="DEBUG",
                ),
            ),
        ),
        SettingAction(
            action_id="show_config",
            label="Toon volledige configuratie",
        ),
    ),
)
