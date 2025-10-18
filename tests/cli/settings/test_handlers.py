from __future__ import annotations

import os

import pytest

from tomic import config as cfg
from tomic.cli.settings import handlers
from tomic.cli.settings.handlers import (
    handle_bool,
    handle_float,
    handle_int,
    handle_log_level,
    handle_path,
    handle_string,
)
from tomic.cli.settings.menu_config import SettingField


@pytest.fixture(autouse=True)
def restore_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Restore cfg.update after each test to avoid bleeding state."""

    original_update = cfg.update
    original_get = cfg.get
    yield
    monkeypatch.setattr(cfg, "update", original_update)
    monkeypatch.setattr(cfg, "get", original_get)


def test_handle_string_updates_value(monkeypatch: pytest.MonkeyPatch) -> None:
    field = SettingField(key="UNDERLYING_EXCHANGE", field_type="str", label="Exchange")
    monkeypatch.setattr(cfg, "get", lambda key, default=None: "SMART")
    updates: dict[str, str] = {}
    monkeypatch.setattr(cfg, "update", lambda values: updates.update(values))

    handle_string(field, prompt_func=lambda text, default=None: "ISE")

    assert updates == {"UNDERLYING_EXCHANGE": "ISE"}


def test_handle_path_skips_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    field = SettingField(key="EXPORT_DIR", field_type="path")
    monkeypatch.setattr(cfg, "get", lambda key, default=None: "exports")
    updates: dict[str, str] = {}
    monkeypatch.setattr(cfg, "update", lambda values: updates.update(values))

    handle_path(field, prompt_func=lambda text: "")

    assert updates == {}


def test_handle_int_converts_value(monkeypatch: pytest.MonkeyPatch) -> None:
    field = SettingField(key="IB_CLIENT_ID", field_type="int")
    monkeypatch.setattr(cfg, "get", lambda key, default=None: 100)
    updates: dict[str, int] = {}
    monkeypatch.setattr(cfg, "update", lambda values: updates.update(values))

    handle_int(field, prompt_func=lambda text: "123")

    assert updates == {"IB_CLIENT_ID": 123}


def test_handle_int_invalid_input(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    field = SettingField(key="IB_CLIENT_ID", field_type="int")
    monkeypatch.setattr(cfg, "get", lambda key, default=None: 100)
    updates: dict[str, int] = {}
    monkeypatch.setattr(cfg, "update", lambda values: updates.update(values))

    handle_int(field, prompt_func=lambda text: "oops")

    captured = capsys.readouterr()
    assert "Ongeldige waarde" in captured.out
    assert updates == {}


def test_handle_float_converts_value(monkeypatch: pytest.MonkeyPatch) -> None:
    field = SettingField(key="INTEREST_RATE", field_type="float")
    monkeypatch.setattr(cfg, "get", lambda key, default=None: 0.05)
    updates: dict[str, float] = {}
    monkeypatch.setattr(cfg, "update", lambda values: updates.update(values))

    handle_float(field, prompt_func=lambda text: "0.75")

    assert updates == {"INTEREST_RATE": 0.75}


def test_handle_bool_uses_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    field = SettingField(key="USE_HISTORICAL_IV_WHEN_CLOSED", field_type="bool")
    monkeypatch.setattr(cfg, "get", lambda key, default=None: False)
    updates: dict[str, bool] = {}
    monkeypatch.setattr(cfg, "update", lambda values: updates.update(values))

    handle_bool(field, prompt_yes_no_func=lambda text, default: True)

    assert updates == {"USE_HISTORICAL_IV_WHEN_CLOSED": True}


def test_handle_log_level_updates_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    field = SettingField(
        key="LOG_LEVEL",
        field_type="log_level",
        label="Stel logniveau in op DEBUG",
        log_level="DEBUG",
    )
    updates: dict[str, str] = {}
    monkeypatch.setattr(cfg, "update", lambda values: updates.update(values))

    called: dict[str, bool] = {}
    monkeypatch.setattr(handlers, "setup_logging", lambda: called.setdefault("called", True))
    monkeypatch.delenv("TOMIC_LOG_LEVEL", raising=False)

    handle_log_level(field)

    assert updates == {"LOG_LEVEL": "DEBUG"}
    assert os.environ["TOMIC_LOG_LEVEL"] == "DEBUG"
    assert called["called"] is True
