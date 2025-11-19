"""Comprehensive tests for exit config functions in _config.py.

These tests ensure that all exit_*_config() functions handle
invalid, missing, and edge-case configuration values robustly.
"""

from __future__ import annotations

from typing import Any

import pytest

from tomic.services import _config


def _cfg_with_exit_options(options: dict[str, Any]):
    """Helper to create a fake cfg_value that returns EXIT_ORDER_OPTIONS."""

    def _fake_cfg_value(key: str, default: Any) -> Any:
        if key == "EXIT_ORDER_OPTIONS":
            return options
        return default

    return _fake_cfg_value


def _cfg_with_values(values: dict[str, Any]):
    """Helper to create a fake cfg_value that returns specific values."""

    def _fake_cfg_value(key: str, default: Any) -> Any:
        return values.get(key, default)

    return _fake_cfg_value


# ===================================================================
# exit_spread_config tests
# ===================================================================


def test_exit_spread_config_defaults_when_unset(monkeypatch):
    """exit_spread_config returns defaults when EXIT_ORDER_OPTIONS is unset."""
    monkeypatch.setattr(_config, "cfg_value", _cfg_with_exit_options({}))

    result = _config.exit_spread_config()

    assert result["absolute"] == _config._DEFAULT_EXIT_SPREAD_ABSOLUTE
    assert result["relative"] == _config._DEFAULT_EXIT_SPREAD_RELATIVE
    assert result["max_quote_age"] == _config._DEFAULT_EXIT_MAX_QUOTE_AGE


def test_exit_spread_config_with_valid_values(monkeypatch):
    """exit_spread_config accepts valid spread configuration."""
    monkeypatch.setattr(
        _config,
        "cfg_value",
        _cfg_with_exit_options({
            "spread": {
                "absolute": 0.75,
                "relative": 0.15,
                "max_quote_age": 3.0,
            }
        }),
    )

    result = _config.exit_spread_config()

    assert result["absolute"] == 0.75
    assert result["relative"] == 0.15
    assert result["max_quote_age"] == 3.0


def test_exit_spread_config_with_string_values(monkeypatch):
    """exit_spread_config converts valid string values to floats."""
    monkeypatch.setattr(
        _config,
        "cfg_value",
        _cfg_with_exit_options({
            "spread": {
                "absolute": "0.90",
                "relative": "0.20",
                "max_quote_age": "4.5",
            }
        }),
    )

    result = _config.exit_spread_config()

    assert result["absolute"] == 0.90
    assert result["relative"] == 0.20
    assert result["max_quote_age"] == 4.5


def test_exit_spread_config_with_invalid_values(monkeypatch):
    """exit_spread_config falls back to defaults for invalid values."""
    monkeypatch.setattr(
        _config,
        "cfg_value",
        _cfg_with_exit_options({
            "spread": {
                "absolute": "invalid",
                "relative": None,
                "max_quote_age": {},
            }
        }),
    )

    result = _config.exit_spread_config()

    assert result["absolute"] == _config._DEFAULT_EXIT_SPREAD_ABSOLUTE
    assert result["relative"] == _config._DEFAULT_EXIT_SPREAD_RELATIVE
    assert result["max_quote_age"] == _config._DEFAULT_EXIT_MAX_QUOTE_AGE


def test_exit_spread_config_clamps_negative_values(monkeypatch):
    """exit_spread_config clamps negative values to 0.0."""
    monkeypatch.setattr(
        _config,
        "cfg_value",
        _cfg_with_exit_options({
            "spread": {
                "absolute": -1.0,
                "relative": -0.5,
                "max_quote_age": -2.0,
            }
        }),
    )

    result = _config.exit_spread_config()

    assert result["absolute"] == 0.0
    assert result["relative"] == 0.0
    assert result["max_quote_age"] == 0.0


def test_exit_spread_config_with_env_fallback(monkeypatch):
    """exit_spread_config uses environment variables as fallback."""
    monkeypatch.setattr(
        _config,
        "cfg_value",
        _cfg_with_values({
            "EXIT_ORDER_OPTIONS": {},
            "EXIT_SPREAD_ABSOLUTE": 1.25,
            "EXIT_SPREAD_RELATIVE": 0.25,
            "EXIT_MAX_QUOTE_AGE": 7.0,
        }),
    )

    result = _config.exit_spread_config()

    assert result["absolute"] == 1.25
    assert result["relative"] == 0.25
    assert result["max_quote_age"] == 7.0


# ===================================================================
# exit_repricer_config tests
# ===================================================================


def test_exit_repricer_config_defaults_when_unset(monkeypatch):
    """exit_repricer_config returns defaults when EXIT_ORDER_OPTIONS is unset."""
    monkeypatch.setattr(_config, "cfg_value", _cfg_with_exit_options({}))

    result = _config.exit_repricer_config()

    assert result["enabled"] is True
    assert result["wait_seconds"] == _config._DEFAULT_EXIT_REPRICER_WAIT


def test_exit_repricer_config_with_valid_values(monkeypatch):
    """exit_repricer_config accepts valid repricer configuration."""
    monkeypatch.setattr(
        _config,
        "cfg_value",
        _cfg_with_exit_options({
            "repricer": {
                "enabled": False,
                "wait_seconds": 15.0,
            }
        }),
    )

    result = _config.exit_repricer_config()

    assert result["enabled"] is False
    assert result["wait_seconds"] == 15.0


def test_exit_repricer_config_with_string_enabled(monkeypatch):
    """exit_repricer_config converts string boolean values."""
    monkeypatch.setattr(
        _config,
        "cfg_value",
        _cfg_with_exit_options({
            "repricer": {
                "enabled": "false",
                "wait_seconds": "20.5",
            }
        }),
    )

    result = _config.exit_repricer_config()

    assert result["enabled"] is False
    assert result["wait_seconds"] == 20.5


def test_exit_repricer_config_clamps_negative_wait(monkeypatch):
    """exit_repricer_config clamps negative wait_seconds to 0.0."""
    monkeypatch.setattr(
        _config,
        "cfg_value",
        _cfg_with_exit_options({
            "repricer": {
                "wait_seconds": -5.0,
            }
        }),
    )

    result = _config.exit_repricer_config()

    assert result["wait_seconds"] == 0.0


# ===================================================================
# exit_fallback_config tests
# ===================================================================


def test_exit_fallback_config_defaults_when_unset(monkeypatch):
    """exit_fallback_config returns defaults when EXIT_ORDER_OPTIONS is unset."""
    monkeypatch.setattr(_config, "cfg_value", _cfg_with_exit_options({}))

    result = _config.exit_fallback_config()

    assert result["allow_preview"] is False
    assert result["allowed_sources"] == set()


def test_exit_fallback_config_with_valid_values(monkeypatch):
    """exit_fallback_config accepts valid fallback configuration."""
    monkeypatch.setattr(
        _config,
        "cfg_value",
        _cfg_with_exit_options({
            "fallback": {
                "allow_preview": True,
                "allowed_sources": ["true", "model", "preview"],
            }
        }),
    )

    result = _config.exit_fallback_config()

    assert result["allow_preview"] is True
    assert result["allowed_sources"] == {"true", "model", "preview"}


def test_exit_fallback_config_normalizes_sources(monkeypatch):
    """exit_fallback_config normalizes allowed_sources to lowercase."""
    monkeypatch.setattr(
        _config,
        "cfg_value",
        _cfg_with_exit_options({
            "fallback": {
                "allowed_sources": ["TRUE", " Model ", "PREVIEW"],
            }
        }),
    )

    result = _config.exit_fallback_config()

    assert result["allowed_sources"] == {"true", "model", "preview"}


def test_exit_fallback_config_skips_empty_sources(monkeypatch):
    """exit_fallback_config skips empty string sources."""
    monkeypatch.setattr(
        _config,
        "cfg_value",
        _cfg_with_exit_options({
            "fallback": {
                "allowed_sources": ["true", "", "  ", "model"],
            }
        }),
    )

    result = _config.exit_fallback_config()

    assert result["allowed_sources"] == {"true", "model"}


def test_exit_fallback_config_handles_non_iterable_sources(monkeypatch):
    """exit_fallback_config handles non-iterable allowed_sources."""
    monkeypatch.setattr(
        _config,
        "cfg_value",
        _cfg_with_exit_options({
            "fallback": {
                "allowed_sources": "not_a_list",
            }
        }),
    )

    result = _config.exit_fallback_config()

    # Should return empty set without crashing
    assert result["allowed_sources"] == set()


# ===================================================================
# exit_force_exit_config tests
# ===================================================================


def test_exit_force_exit_config_defaults_when_unset(monkeypatch):
    """exit_force_exit_config returns defaults when EXIT_ORDER_OPTIONS is unset."""
    monkeypatch.setattr(_config, "cfg_value", _cfg_with_exit_options({}))

    result = _config.exit_force_exit_config()

    assert result["enabled"] is False
    assert result["market_order"] is False
    assert result["limit_cap"] is None


def test_exit_force_exit_config_accepts_boolean_true(monkeypatch):
    """exit_force_exit_config accepts boolean True for force_exit."""
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
    """exit_force_exit_config accepts boolean False for force_exit."""
    monkeypatch.setattr(
        _config,
        "cfg_value",
        _cfg_with_exit_options({"force_exit": False}),
    )

    result = _config.exit_force_exit_config()

    assert result["enabled"] is False
    assert result["market_order"] is False
    assert result["limit_cap"] is None


def test_exit_force_exit_config_with_mapping(monkeypatch):
    """exit_force_exit_config accepts mapping for force_exit."""
    monkeypatch.setattr(
        _config,
        "cfg_value",
        _cfg_with_exit_options({
            "force_exit": {
                "enabled": True,
                "market_order": True,
            }
        }),
    )

    result = _config.exit_force_exit_config()

    assert result["enabled"] is True
    assert result["market_order"] is True
    assert result["limit_cap"] is None


def test_exit_force_exit_config_with_absolute_limit_cap(monkeypatch):
    """exit_force_exit_config accepts absolute limit_cap."""
    monkeypatch.setattr(
        _config,
        "cfg_value",
        _cfg_with_exit_options({
            "force_exit": {
                "enabled": True,
                "limit_cap": {
                    "type": "absolute",
                    "value": 0.50,
                },
            }
        }),
    )

    result = _config.exit_force_exit_config()

    assert result["enabled"] is True
    assert result["limit_cap"] == {"type": "absolute", "value": 0.50}


def test_exit_force_exit_config_with_bps_limit_cap(monkeypatch):
    """exit_force_exit_config accepts bps limit_cap."""
    monkeypatch.setattr(
        _config,
        "cfg_value",
        _cfg_with_exit_options({
            "force_exit": {
                "enabled": True,
                "limit_cap": {
                    "type": "bps",
                    "value": 100.0,
                },
            }
        }),
    )

    result = _config.exit_force_exit_config()

    assert result["enabled"] is True
    assert result["limit_cap"] == {"type": "bps", "value": 100.0}


def test_exit_force_exit_config_ignores_invalid_limit_cap_type(monkeypatch):
    """exit_force_exit_config ignores invalid limit_cap type."""
    monkeypatch.setattr(
        _config,
        "cfg_value",
        _cfg_with_exit_options({
            "force_exit": {
                "enabled": True,
                "limit_cap": {
                    "type": "invalid_type",
                    "value": 0.50,
                },
            }
        }),
    )

    result = _config.exit_force_exit_config()

    assert result["enabled"] is True
    assert result["limit_cap"] is None


def test_exit_force_exit_config_ignores_zero_limit_cap_value(monkeypatch):
    """exit_force_exit_config ignores zero limit_cap value."""
    monkeypatch.setattr(
        _config,
        "cfg_value",
        _cfg_with_exit_options({
            "force_exit": {
                "limit_cap": {
                    "type": "absolute",
                    "value": 0.0,
                },
            }
        }),
    )

    result = _config.exit_force_exit_config()

    assert result["limit_cap"] is None


def test_exit_force_exit_config_ignores_negative_limit_cap_value(monkeypatch):
    """exit_force_exit_config ignores negative limit_cap value."""
    monkeypatch.setattr(
        _config,
        "cfg_value",
        _cfg_with_exit_options({
            "force_exit": {
                "limit_cap": {
                    "type": "absolute",
                    "value": -0.50,
                },
            }
        }),
    )

    result = _config.exit_force_exit_config()

    assert result["limit_cap"] is None


# ===================================================================
# exit_price_ladder_config tests
# ===================================================================


def test_exit_price_ladder_config_defaults_when_unset(monkeypatch):
    """exit_price_ladder_config returns defaults when EXIT_ORDER_OPTIONS is unset."""
    monkeypatch.setattr(_config, "cfg_value", _cfg_with_exit_options({}))

    result = _config.exit_price_ladder_config()

    assert result["enabled"] is False
    assert result["steps"] == []
    assert result["step_wait_seconds"] == 0.0
    assert result["max_duration_seconds"] == 0.0


def test_exit_price_ladder_config_with_valid_values(monkeypatch):
    """exit_price_ladder_config accepts valid price_ladder configuration."""
    monkeypatch.setattr(
        _config,
        "cfg_value",
        _cfg_with_exit_options({
            "price_ladder": {
                "enabled": True,
                "steps": [0.05, 0.10, 0.15],
                "step_wait_seconds": 5.0,
                "max_duration_seconds": 30.0,
            }
        }),
    )

    result = _config.exit_price_ladder_config()

    assert result["enabled"] is True
    assert result["steps"] == [0.05, 0.10, 0.15]
    assert result["step_wait_seconds"] == 5.0
    assert result["max_duration_seconds"] == 30.0


def test_exit_price_ladder_config_with_step_wait_s(monkeypatch):
    """exit_price_ladder_config supports step_wait_s naming convention."""
    monkeypatch.setattr(
        _config,
        "cfg_value",
        _cfg_with_exit_options({
            "price_ladder": {
                "enabled": True,
                "step_wait_s": 7.5,
            }
        }),
    )

    result = _config.exit_price_ladder_config()

    assert result["step_wait_seconds"] == 7.5


def test_exit_price_ladder_config_with_step_wait_ms(monkeypatch):
    """exit_price_ladder_config converts step_wait_ms to seconds."""
    monkeypatch.setattr(
        _config,
        "cfg_value",
        _cfg_with_exit_options({
            "price_ladder": {
                "enabled": True,
                "step_wait_ms": 5000.0,  # 5000ms = 5s
            }
        }),
    )

    result = _config.exit_price_ladder_config()

    assert result["step_wait_seconds"] == 5.0


def test_exit_price_ladder_config_skips_invalid_steps(monkeypatch):
    """exit_price_ladder_config skips invalid step values."""
    monkeypatch.setattr(
        _config,
        "cfg_value",
        _cfg_with_exit_options({
            "price_ladder": {
                "enabled": True,
                "steps": [0.05, "invalid", None, 0.15, {}],
            }
        }),
    )

    result = _config.exit_price_ladder_config()

    assert result["steps"] == [0.05, 0.15]


def test_exit_price_ladder_config_handles_non_iterable_steps(monkeypatch):
    """exit_price_ladder_config handles non-iterable steps."""
    monkeypatch.setattr(
        _config,
        "cfg_value",
        _cfg_with_exit_options({
            "price_ladder": {
                "enabled": True,
                "steps": "not_a_list",
            }
        }),
    )

    result = _config.exit_price_ladder_config()

    # Should return empty list without crashing
    assert result["steps"] == []


def test_exit_price_ladder_config_clamps_negative_wait(monkeypatch):
    """exit_price_ladder_config clamps negative wait times to 0.0."""
    monkeypatch.setattr(
        _config,
        "cfg_value",
        _cfg_with_exit_options({
            "price_ladder": {
                "step_wait_seconds": -5.0,
                "max_duration_seconds": -10.0,
            }
        }),
    )

    result = _config.exit_price_ladder_config()

    assert result["step_wait_seconds"] == 0.0
    assert result["max_duration_seconds"] == 0.0


def test_exit_price_ladder_config_with_max_duration_s(monkeypatch):
    """exit_price_ladder_config supports max_duration_s naming convention."""
    monkeypatch.setattr(
        _config,
        "cfg_value",
        _cfg_with_exit_options({
            "price_ladder": {
                "max_duration_s": 45.0,
            }
        }),
    )

    result = _config.exit_price_ladder_config()

    assert result["max_duration_seconds"] == 45.0
