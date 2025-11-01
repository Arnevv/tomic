from __future__ import annotations

from typing import Any

from tomic.services import _config


def _cfg_with_exit_options(options: dict[str, Any]):
    def _fake_cfg_value(key: str, default: Any) -> Any:
        if key == "EXIT_ORDER_OPTIONS":
            return options
        return default

    return _fake_cfg_value


def test_exit_force_exit_config_accepts_boolean_true(monkeypatch):
    monkeypatch.setattr(
        _config,
        "cfg_value",
        _cfg_with_exit_options({"force_exit": True}),
    )

    result = _config.exit_force_exit_config()

    assert result["enabled"] is True
    assert result["market_order"] is False
    assert result["limit_cap"] is None


def test_exit_force_exit_config_accepts_boolean_false(monkeypatch):
    monkeypatch.setattr(
        _config,
        "cfg_value",
        _cfg_with_exit_options({"force_exit": False}),
    )

    result = _config.exit_force_exit_config()

    assert result["enabled"] is False
    assert result["market_order"] is False
    assert result["limit_cap"] is None
