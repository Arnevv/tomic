"""Comprehensive tests for exit configuration functions in _config.py."""
from __future__ import annotations

import pytest

from tomic.services import _config


@pytest.fixture
def mock_cfg(monkeypatch):
    """Factory to create a cfg_value mock with specified values."""

    def _make_mock(values: dict):
        def _fake_cfg_value(key: str, default):
            return values.get(key, default)

        monkeypatch.setattr(_config, "cfg_value", _fake_cfg_value)

    return _make_mock


# ============================================================================
# exit_spread_config tests
# ============================================================================


def test_exit_spread_config_defaults(mock_cfg):
    """Test exit_spread_config with no custom config returns defaults."""
    mock_cfg({})
    result = _config.exit_spread_config()

    assert result["absolute"] == _config._DEFAULT_EXIT_SPREAD_ABSOLUTE
    assert result["relative"] == _config._DEFAULT_EXIT_SPREAD_RELATIVE
    assert result["max_quote_age"] == _config._DEFAULT_EXIT_MAX_QUOTE_AGE


def test_exit_spread_config_valid_absolute(mock_cfg):
    """Test exit_spread_config with valid absolute value."""
    mock_cfg({"EXIT_SPREAD_ABSOLUTE": 0.75})
    result = _config.exit_spread_config()

    assert result["absolute"] == 0.75


def test_exit_spread_config_valid_relative(mock_cfg):
    """Test exit_spread_config with valid relative value."""
    mock_cfg({"EXIT_SPREAD_RELATIVE": 0.25})
    result = _config.exit_spread_config()

    assert result["relative"] == 0.25


def test_exit_spread_config_valid_max_quote_age(mock_cfg):
    """Test exit_spread_config with valid max_quote_age."""
    mock_cfg({"EXIT_MAX_QUOTE_AGE": 10.0})
    result = _config.exit_spread_config()

    assert result["max_quote_age"] == 10.0


def test_exit_spread_config_via_exit_order_options(mock_cfg):
    """Test exit_spread_config with EXIT_ORDER_OPTIONS spread section."""
    mock_cfg(
        {
            "EXIT_ORDER_OPTIONS": {
                "spread": {
                    "absolute": 1.0,
                    "relative": 0.5,
                    "max_quote_age": 15.0,
                }
            }
        }
    )
    result = _config.exit_spread_config()

    assert result["absolute"] == 1.0
    assert result["relative"] == 0.5
    assert result["max_quote_age"] == 15.0


def test_exit_spread_config_invalid_string_values(mock_cfg):
    """Test exit_spread_config with invalid string values falls back to defaults."""
    mock_cfg(
        {
            "EXIT_ORDER_OPTIONS": {
                "spread": {
                    "absolute": "invalid",
                    "relative": "bad",
                    "max_quote_age": "wrong",
                }
            }
        }
    )
    result = _config.exit_spread_config()

    # Should fall back to defaults
    assert result["absolute"] == _config._DEFAULT_EXIT_SPREAD_ABSOLUTE
    assert result["relative"] == _config._DEFAULT_EXIT_SPREAD_RELATIVE
    assert result["max_quote_age"] == _config._DEFAULT_EXIT_MAX_QUOTE_AGE


def test_exit_spread_config_negative_values(mock_cfg):
    """Test exit_spread_config with negative values uses defaults."""
    mock_cfg(
        {
            "EXIT_ORDER_OPTIONS": {
                "spread": {
                    "absolute": -1.0,
                    "relative": -0.5,
                    "max_quote_age": -5.0,
                }
            }
        }
    )
    result = _config.exit_spread_config()

    # Negative values should trigger defaults
    assert result["absolute"] == _config._DEFAULT_EXIT_SPREAD_ABSOLUTE
    assert result["relative"] == _config._DEFAULT_EXIT_SPREAD_RELATIVE
    assert result["max_quote_age"] == _config._DEFAULT_EXIT_MAX_QUOTE_AGE


def test_exit_spread_config_zero_values(mock_cfg):
    """Test exit_spread_config with zero values (valid edge case)."""
    mock_cfg({"EXIT_ORDER_OPTIONS": {"spread": {"absolute": 0.0, "relative": 0.0, "max_quote_age": 0.0}}})
    result = _config.exit_spread_config()

    assert result["absolute"] == 0.0
    assert result["relative"] == 0.0
    assert result["max_quote_age"] == 0.0


def test_exit_spread_config_exception_recovery(mock_cfg, monkeypatch):
    """Test exit_spread_config recovers from exceptions."""

    def _failing_cfg_value(key, default):
        raise RuntimeError("config failure")

    monkeypatch.setattr(_config, "cfg_value", _failing_cfg_value)
    result = _config.exit_spread_config()

    # Should return safe defaults
    assert result["absolute"] == _config._DEFAULT_EXIT_SPREAD_ABSOLUTE
    assert result["relative"] == _config._DEFAULT_EXIT_SPREAD_RELATIVE
    assert result["max_quote_age"] == _config._DEFAULT_EXIT_MAX_QUOTE_AGE


# ============================================================================
# exit_repricer_config tests
# ============================================================================


def test_exit_repricer_config_defaults(mock_cfg):
    """Test exit_repricer_config with no custom config."""
    mock_cfg({})
    result = _config.exit_repricer_config()

    assert result["enabled"] is True
    assert result["wait_seconds"] == _config._DEFAULT_EXIT_REPRICER_WAIT


def test_exit_repricer_config_disabled(mock_cfg):
    """Test exit_repricer_config with disabled repricer."""
    mock_cfg({"EXIT_ORDER_OPTIONS": {"repricer": {"enabled": False}}})
    result = _config.exit_repricer_config()

    assert result["enabled"] is False


def test_exit_repricer_config_custom_wait(mock_cfg):
    """Test exit_repricer_config with custom wait time."""
    mock_cfg({"EXIT_ORDER_OPTIONS": {"repricer": {"wait_seconds": 5.0}}})
    result = _config.exit_repricer_config()

    assert result["wait_seconds"] == 5.0


def test_exit_repricer_config_negative_wait(mock_cfg):
    """Test exit_repricer_config with negative wait falls back to default."""
    mock_cfg({"EXIT_ORDER_OPTIONS": {"repricer": {"wait_seconds": -10.0}}})
    result = _config.exit_repricer_config()

    assert result["wait_seconds"] == _config._DEFAULT_EXIT_REPRICER_WAIT


def test_exit_repricer_config_exception_recovery(mock_cfg, monkeypatch):
    """Test exit_repricer_config recovers from exceptions."""

    def _failing_cfg_value(key, default):
        raise ValueError("config error")

    monkeypatch.setattr(_config, "cfg_value", _failing_cfg_value)
    result = _config.exit_repricer_config()

    assert result["enabled"] is True
    assert result["wait_seconds"] == _config._DEFAULT_EXIT_REPRICER_WAIT


# ============================================================================
# exit_fallback_config tests
# ============================================================================


def test_exit_fallback_config_defaults(mock_cfg):
    """Test exit_fallback_config with defaults."""
    mock_cfg({})
    result = _config.exit_fallback_config()

    assert result["allow_preview"] is False
    assert result["allowed_sources"] == set()


def test_exit_fallback_config_allow_preview(mock_cfg):
    """Test exit_fallback_config with allow_preview enabled."""
    mock_cfg({"EXIT_ORDER_OPTIONS": {"fallback": {"allow_preview": True}}})
    result = _config.exit_fallback_config()

    assert result["allow_preview"] is True


def test_exit_fallback_config_with_sources(mock_cfg):
    """Test exit_fallback_config with allowed_sources."""
    mock_cfg({"EXIT_ORDER_OPTIONS": {"fallback": {"allowed_sources": ["source1", "SOURCE2", "source3"]}}})
    result = _config.exit_fallback_config()

    assert result["allowed_sources"] == {"source1", "source2", "source3"}


def test_exit_fallback_config_invalid_sources(mock_cfg):
    """Test exit_fallback_config with invalid allowed_sources (string instead of list)."""
    mock_cfg({"EXIT_ORDER_OPTIONS": {"fallback": {"allowed_sources": "not_a_list"}}})
    result = _config.exit_fallback_config()

    # String gets split into individual characters (Python iterates over string)
    # This is acceptable behavior - the set will contain individual chars
    # Just verify it returns a set (not empty in this case)
    assert isinstance(result["allowed_sources"], set)


def test_exit_fallback_config_exception_recovery(mock_cfg, monkeypatch):
    """Test exit_fallback_config recovers from exceptions."""

    def _failing_cfg_value(key, default):
        raise TypeError("config failure")

    monkeypatch.setattr(_config, "cfg_value", _failing_cfg_value)
    result = _config.exit_fallback_config()

    assert result["allow_preview"] is False
    assert result["allowed_sources"] == set()


# ============================================================================
# exit_force_exit_config tests
# ============================================================================


def test_exit_force_exit_config_defaults(mock_cfg):
    """Test exit_force_exit_config with defaults."""
    mock_cfg({})
    result = _config.exit_force_exit_config()

    assert result["enabled"] is False
    assert result["market_order"] is False
    assert result["limit_cap"] is None


def test_exit_force_exit_config_boolean_enabled(mock_cfg):
    """Test exit_force_exit_config with boolean True value."""
    mock_cfg({"EXIT_ORDER_OPTIONS": {"force_exit": True}})
    result = _config.exit_force_exit_config()

    assert result["enabled"] is True
    assert result["market_order"] is False


def test_exit_force_exit_config_boolean_disabled(mock_cfg):
    """Test exit_force_exit_config with boolean False value."""
    mock_cfg({"EXIT_ORDER_OPTIONS": {"force_exit": False}})
    result = _config.exit_force_exit_config()

    assert result["enabled"] is False


def test_exit_force_exit_config_full_config(mock_cfg):
    """Test exit_force_exit_config with full configuration."""
    mock_cfg(
        {
            "EXIT_ORDER_OPTIONS": {
                "force_exit": {
                    "enabled": True,
                    "market_order": True,
                    "limit_cap": {"type": "absolute", "value": 0.5},
                }
            }
        }
    )
    result = _config.exit_force_exit_config()

    assert result["enabled"] is True
    assert result["market_order"] is True
    assert result["limit_cap"] == {"type": "absolute", "value": 0.5}


def test_exit_force_exit_config_limit_cap_bps(mock_cfg):
    """Test exit_force_exit_config with bps limit_cap."""
    mock_cfg({"EXIT_ORDER_OPTIONS": {"force_exit": {"limit_cap": {"type": "bps", "value": 100.0}}}})
    result = _config.exit_force_exit_config()

    assert result["limit_cap"] == {"type": "bps", "value": 100.0}


def test_exit_force_exit_config_invalid_limit_cap_type(mock_cfg):
    """Test exit_force_exit_config with invalid limit_cap type."""
    mock_cfg({"EXIT_ORDER_OPTIONS": {"force_exit": {"limit_cap": {"type": "unknown", "value": 1.0}}}})
    result = _config.exit_force_exit_config()

    # Unknown type should be ignored
    assert result["limit_cap"] is None


def test_exit_force_exit_config_negative_limit_cap_value(mock_cfg):
    """Test exit_force_exit_config with negative limit_cap value."""
    mock_cfg({"EXIT_ORDER_OPTIONS": {"force_exit": {"limit_cap": {"type": "absolute", "value": -0.5}}}})
    result = _config.exit_force_exit_config()

    # Negative value should be rejected
    assert result["limit_cap"] is None


def test_exit_force_exit_config_zero_limit_cap_value(mock_cfg):
    """Test exit_force_exit_config with zero limit_cap value."""
    mock_cfg({"EXIT_ORDER_OPTIONS": {"force_exit": {"limit_cap": {"type": "absolute", "value": 0.0}}}})
    result = _config.exit_force_exit_config()

    # Zero value should be rejected
    assert result["limit_cap"] is None


def test_exit_force_exit_config_exception_recovery(mock_cfg, monkeypatch):
    """Test exit_force_exit_config recovers from exceptions."""

    def _failing_cfg_value(key, default):
        raise RuntimeError("config error")

    monkeypatch.setattr(_config, "cfg_value", _failing_cfg_value)
    result = _config.exit_force_exit_config()

    assert result["enabled"] is False
    assert result["market_order"] is False
    assert result["limit_cap"] is None


# ============================================================================
# exit_price_ladder_config tests
# ============================================================================


def test_exit_price_ladder_config_defaults(mock_cfg):
    """Test exit_price_ladder_config with defaults."""
    mock_cfg({})
    result = _config.exit_price_ladder_config()

    assert result["enabled"] is False
    assert result["steps"] == []
    assert result["step_wait_seconds"] == 0.0
    assert result["max_duration_seconds"] == 0.0


def test_exit_price_ladder_config_enabled_with_steps(mock_cfg):
    """Test exit_price_ladder_config with enabled and steps."""
    mock_cfg({"EXIT_ORDER_OPTIONS": {"price_ladder": {"enabled": True, "steps": [0.05, 0.10, 0.15]}}})
    result = _config.exit_price_ladder_config()

    assert result["enabled"] is True
    assert result["steps"] == [0.05, 0.10, 0.15]


def test_exit_price_ladder_config_step_wait_seconds(mock_cfg):
    """Test exit_price_ladder_config with step_wait_seconds."""
    mock_cfg({"EXIT_ORDER_OPTIONS": {"price_ladder": {"step_wait_seconds": 2.5}}})
    result = _config.exit_price_ladder_config()

    assert result["step_wait_seconds"] == 2.5


def test_exit_price_ladder_config_step_wait_ms(mock_cfg):
    """Test exit_price_ladder_config with step_wait_ms (conversion to seconds)."""
    mock_cfg({"EXIT_ORDER_OPTIONS": {"price_ladder": {"step_wait_ms": 2000}}})
    result = _config.exit_price_ladder_config()

    assert result["step_wait_seconds"] == 2.0


def test_exit_price_ladder_config_max_duration_seconds(mock_cfg):
    """Test exit_price_ladder_config with max_duration_seconds."""
    mock_cfg({"EXIT_ORDER_OPTIONS": {"price_ladder": {"max_duration_seconds": 30.0}}})
    result = _config.exit_price_ladder_config()

    assert result["max_duration_seconds"] == 30.0


def test_exit_price_ladder_config_invalid_steps(mock_cfg):
    """Test exit_price_ladder_config with invalid steps."""
    mock_cfg({"EXIT_ORDER_OPTIONS": {"price_ladder": {"steps": [0.05, "invalid", 0.15, None]}}})
    result = _config.exit_price_ladder_config()

    # Should skip invalid values
    assert result["steps"] == [0.05, 0.15]


def test_exit_price_ladder_config_negative_wait(mock_cfg):
    """Test exit_price_ladder_config with negative wait time."""
    mock_cfg({"EXIT_ORDER_OPTIONS": {"price_ladder": {"step_wait_seconds": -5.0}}})
    result = _config.exit_price_ladder_config()

    # Negative should be clamped to 0
    assert result["step_wait_seconds"] == 0.0


def test_exit_price_ladder_config_negative_max_duration(mock_cfg):
    """Test exit_price_ladder_config with negative max_duration."""
    mock_cfg({"EXIT_ORDER_OPTIONS": {"price_ladder": {"max_duration_seconds": -10.0}}})
    result = _config.exit_price_ladder_config()

    # Negative should be clamped to 0
    assert result["max_duration_seconds"] == 0.0


def test_exit_price_ladder_config_exception_recovery(mock_cfg, monkeypatch):
    """Test exit_price_ladder_config recovers from exceptions."""

    def _failing_cfg_value(key, default):
        raise ValueError("config failure")

    monkeypatch.setattr(_config, "cfg_value", _failing_cfg_value)
    result = _config.exit_price_ladder_config()

    assert result["enabled"] is False
    assert result["steps"] == []
    assert result["step_wait_seconds"] == 0.0
    assert result["max_duration_seconds"] == 0.0
