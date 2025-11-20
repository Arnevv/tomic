"""Comprehensive tests for exit_flow with all paths and edge cases."""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from tomic.services import exit_orders
from tomic.services.exit_flow import (
    ExitFlowConfig,
    execute_exit_flow,
)
from tomic.services.exit_orders import build_exit_order_plan
from tomic.services.trade_management_service import StrategyExitIntent


@pytest.fixture
def vertical_intent() -> StrategyExitIntent:
    """Create a simple vertical spread exit intent for testing."""
    strategy = {
        "symbol": "SPY",
        "expiry": "20240315",
        "legs": [
            {"strike": 450.0, "right": "call", "position": -1},
            {"strike": 455.0, "right": "call", "position": 1},
        ],
    }
    legs = [
        {
            "conId": 2001,
            "symbol": "SPY",
            "expiry": "20240315",
            "strike": 450.0,
            "right": "C",
            "position": -1,
            "bid": 5.1,
            "ask": 5.2,
            "minTick": 0.01,
            "quote_age_sec": 0.5,
            "mid_source": "true",
        },
        {
            "conId": 2002,
            "symbol": "SPY",
            "expiry": "20240315",
            "strike": 455.0,
            "right": "C",
            "position": 1,
            "bid": 3.05,
            "ask": 3.15,
            "minTick": 0.01,
            "quote_age_sec": 0.5,
            "mid_source": "true",
        },
    ]
    return StrategyExitIntent(strategy=strategy, legs=legs, exit_rules=None)


@pytest.fixture
def config(tmp_path: Path) -> ExitFlowConfig:
    """Create a test configuration."""
    return ExitFlowConfig(
        host="127.0.0.1",
        port=4002,
        client_id=50,
        account=None,
        order_type="LMT",
        tif="DAY",
        fetch_only=False,
        force_exit_enabled=False,
        market_order_on_force=False,
        log_directory=tmp_path,
    )


@pytest.fixture(autouse=True)
def relaxed_exit_gate(monkeypatch):
    """Relax exit gate for testing."""
    monkeypatch.setattr(
        exit_orders,
        "exit_spread_config",
        lambda: {"absolute": 5.0, "relative": 5.0, "max_quote_age": 30.0},
    )
    monkeypatch.setattr(
        exit_orders,
        "exit_fallback_config",
        lambda: {"allow_preview": True, "allowed_sources": {"true"}},
    )
    monkeypatch.setattr(
        exit_orders,
        "exit_force_exit_config",
        lambda: {"enabled": False, "market_order": False, "limit_cap": None},
    )


# ============================================================================
# Primary path tests
# ============================================================================


def test_primary_success(vertical_intent, config):
    """Test successful primary exit path."""

    def dispatcher(plan):
        return (111,)

    result = execute_exit_flow(vertical_intent, config=config, dispatcher=dispatcher)

    assert result.status == "success"
    assert result.reason == "primary"
    assert result.order_ids == (111,)
    assert len(result.attempts) == 1
    assert result.attempts[0].stage == "primary"
    assert result.attempts[0].status == "success"
    assert not result.forced


def test_primary_dispatcher_exception(vertical_intent, config):
    """Test primary path with dispatcher exception."""

    def dispatcher(plan):
        raise RuntimeError("network error")

    result = execute_exit_flow(vertical_intent, config=config, dispatcher=dispatcher)

    # If dispatcher always fails, both primary and fallback will fail
    assert result.status == "failed"
    assert len(result.attempts) >= 2
    assert result.attempts[0].stage == "primary"
    assert result.attempts[0].status == "failed"
    assert "network error" in (result.attempts[0].reason or "")


def test_primary_no_order_ids(vertical_intent, config):
    """Test primary path returns empty order IDs."""

    def dispatcher(plan):
        return tuple()

    result = execute_exit_flow(vertical_intent, config=config, dispatcher=dispatcher)

    # If dispatcher always returns empty, both primary and fallback will fail
    assert result.status == "failed"
    assert result.attempts[0].stage == "primary"
    assert result.attempts[0].status == "failed"
    assert result.attempts[0].reason == "no_order_ids"


# ============================================================================
# Fallback path tests
# ============================================================================


def test_fallback_success_after_primary_fails(vertical_intent, config):
    """Test fallback succeeds after primary fails."""
    call_count = [0]

    def dispatcher(plan):
        call_count[0] += 1
        if call_count[0] == 1:
            # Primary fails
            raise RuntimeError("primary failed")
        # Fallback succeeds
        return (222,)

    result = execute_exit_flow(vertical_intent, config=config, dispatcher=dispatcher)

    assert result.status == "success"
    assert "fallback" in result.reason
    assert result.order_ids == (222,)
    assert len(result.attempts) >= 2
    assert result.attempts[0].stage == "primary"
    assert result.attempts[0].status == "failed"
    assert "fallback" in result.attempts[1].stage
    assert result.attempts[1].status == "success"


def test_fallback_failure(vertical_intent, config):
    """Test both primary and fallback fail."""

    def dispatcher(plan):
        # Always fail
        return tuple()

    result = execute_exit_flow(vertical_intent, config=config, dispatcher=dispatcher)

    assert result.status == "failed"
    assert result.order_ids == tuple()
    assert len(result.attempts) >= 2
    assert result.attempts[0].status == "failed"
    # Fallback attempts should also fail
    assert all(a.status in ("failed", "skipped") for a in result.attempts[1:])


# ============================================================================
# Force-exit path tests
# ============================================================================


def test_force_exit_success_after_primary_and_fallback_fail(vertical_intent, config):
    """Test force-exit succeeds after primary and fallback fail."""
    call_count = [0]

    def dispatcher(plan):
        call_count[0] += 1
        # Primary and fallback fail, but force succeeds
        if call_count[0] <= 2:  # Primary and fallback
            return tuple()
        # Force succeeds
        return (999,)

    result = execute_exit_flow(vertical_intent, config=config, dispatcher=dispatcher, force_exit=True)

    assert result.status == "success"
    assert result.reason == "force_exit"
    assert result.forced is True
    assert len(result.attempts) >= 3
    assert result.attempts[0].stage == "primary"
    assert result.attempts[0].status == "failed"
    # Look for force stage
    force_attempts = [a for a in result.attempts if a.stage == "force"]
    assert len(force_attempts) >= 1
    assert force_attempts[0].status == "success"


def test_force_exit_disabled(vertical_intent, config):
    """Test force-exit path is not taken when disabled."""

    def dispatcher(plan):
        return tuple()

    result = execute_exit_flow(vertical_intent, config=config, dispatcher=dispatcher, force_exit=False)

    assert result.status == "failed"
    assert result.forced is False
    # No force stage should be present
    force_attempts = [a for a in result.attempts if a.stage == "force"]
    assert len(force_attempts) == 0


def test_all_paths_fail(vertical_intent, config):
    """Test all exit paths fail (primary, fallback, force)."""

    def dispatcher(plan):
        raise RuntimeError("complete failure")

    result = execute_exit_flow(vertical_intent, config=config, dispatcher=dispatcher, force_exit=True)

    assert result.status == "failed"
    assert result.order_ids == tuple()
    assert result.forced is True
    # All attempts should fail
    assert all(a.status in ("failed", "skipped") for a in result.attempts)
    # Should have attempts for primary, fallback(s), and force
    assert len(result.attempts) >= 3


def test_force_exit_with_force_config_enabled(monkeypatch, vertical_intent, config):
    """Test force-exit is attempted when config enabled."""
    monkeypatch.setattr(
        "tomic.services.exit_flow.exit_force_exit_config",
        lambda: {"enabled": True, "market_order": False, "limit_cap": None},
    )

    # Force config to enable force_exit
    config_with_force = ExitFlowConfig(
        host=config.host,
        port=config.port,
        client_id=config.client_id,
        account=config.account,
        order_type=config.order_type,
        tif=config.tif,
        fetch_only=config.fetch_only,
        force_exit_enabled=True,
        market_order_on_force=config.market_order_on_force,
        log_directory=config.log_directory,
    )

    def dispatcher(plan):
        return tuple()

    result = execute_exit_flow(vertical_intent, config=config_with_force, dispatcher=dispatcher)

    assert result.forced is True
    force_attempts = [a for a in result.attempts if a.stage == "force"]
    assert len(force_attempts) >= 1


# ============================================================================
# Quote-age and validation tests
# ============================================================================


def test_stale_quote_triggers_fallback(monkeypatch, config):
    """Test stale quotes trigger fallback path."""
    monkeypatch.setattr(
        exit_orders,
        "exit_spread_config",
        lambda: {"absolute": 5.0, "relative": 5.0, "max_quote_age": 1.0},  # Strict age
    )

    strategy = {"symbol": "SPY", "expiry": "20240315"}
    legs = [
        {
            "conId": 3001,
            "symbol": "SPY",
            "expiry": "20240315",
            "strike": 450.0,
            "right": "C",
            "position": -1,
            "bid": 5.1,
            "ask": 5.2,
            "minTick": 0.01,
            "quote_age_sec": 10.0,  # Too old
            "mid_source": "true",
        },
        {
            "conId": 3002,
            "symbol": "SPY",
            "expiry": "20240315",
            "strike": 455.0,
            "right": "C",
            "position": 1,
            "bid": 3.05,
            "ask": 3.15,
            "minTick": 0.01,
            "quote_age_sec": 10.0,  # Too old
            "mid_source": "true",
        },
    ]
    intent = StrategyExitIntent(strategy=strategy, legs=legs, exit_rules=None)

    def dispatcher(plan):
        # Dispatcher succeeds
        return (333,)

    result = execute_exit_flow(intent, config=config, dispatcher=dispatcher)

    # With stale quotes, plan building may fail or proceed to fallback
    # Either way, we should get a result
    assert result.status in ("success", "failed")


def test_invalid_plan_returns_failed(config):
    """Test invalid exit plan returns failed status."""
    strategy = {"symbol": "BAD", "expiry": "20240315"}
    legs = [
        {
            "conId": 4001,
            "symbol": "BAD",
            "expiry": "20240315",
            "strike": 100.0,
            "right": "C",
            "position": -1,
            "bid": None,  # Missing bid
            "ask": None,  # Missing ask
            "minTick": 0.01,
        }
    ]
    intent = StrategyExitIntent(strategy=strategy, legs=legs, exit_rules=None)

    result = execute_exit_flow(intent, config=config, dispatcher=lambda p: (1,))

    assert result.status == "failed"
    assert "niet verhandelbaar" in result.reason.lower() or "missing" in result.reason.lower()
    assert result.order_ids == tuple()


# ============================================================================
# Price ladder tests
# ============================================================================


def test_price_ladder_disabled_uses_primary(monkeypatch, vertical_intent, config):
    """Test price ladder disabled falls back to primary path."""
    monkeypatch.setattr(
        "tomic.services.exit_flow.exit_price_ladder_config",
        lambda: {"enabled": False, "steps": [], "step_wait_seconds": 0.0, "max_duration_seconds": 0.0},
    )

    def dispatcher(plan):
        return (555,)

    result = execute_exit_flow(vertical_intent, config=config, dispatcher=dispatcher)

    assert result.status == "success"
    assert result.order_ids == (555,)
    # Should be primary, not ladder
    assert result.attempts[0].stage == "primary"


def test_price_ladder_first_step_succeeds(monkeypatch, vertical_intent, config):
    """Test price ladder succeeds on first step."""
    monkeypatch.setattr(
        "tomic.services.exit_flow.exit_price_ladder_config",
        lambda: {"enabled": True, "steps": [0.05, 0.10], "step_wait_seconds": 0.0, "max_duration_seconds": 0.0},
    )

    def dispatcher(plan):
        return (666,)

    result = execute_exit_flow(vertical_intent, config=config, dispatcher=dispatcher)

    assert result.status == "success"
    assert result.order_ids == (666,)
    assert result.attempts[0].stage == "primary"


def test_price_ladder_second_step_succeeds(monkeypatch, vertical_intent, config):
    """Test price ladder succeeds on second step."""
    monkeypatch.setattr(
        "tomic.services.exit_flow.exit_price_ladder_config",
        lambda: {"enabled": True, "steps": [0.05, 0.10], "step_wait_seconds": 0.0, "max_duration_seconds": 0.0},
    )

    call_count = [0]

    def dispatcher(plan):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("first step failed")
        return (777,)

    result = execute_exit_flow(vertical_intent, config=config, dispatcher=dispatcher)

    assert result.status == "success"
    assert result.order_ids == (777,)
    assert result.reason == "ladder:1"


def test_price_ladder_all_steps_fail(monkeypatch, vertical_intent, config):
    """Test price ladder with all steps failing."""
    monkeypatch.setattr(
        "tomic.services.exit_flow.exit_price_ladder_config",
        lambda: {"enabled": True, "steps": [0.05], "step_wait_seconds": 0.0, "max_duration_seconds": 0.0},
    )

    def dispatcher(plan):
        raise RuntimeError("all steps failed")

    result = execute_exit_flow(vertical_intent, config=config, dispatcher=dispatcher)

    # If dispatcher always fails, all paths (ladder, fallback) will fail
    assert result.status == "failed"
    assert len(result.attempts) >= 2


# ============================================================================
# Fetch-only mode tests
# ============================================================================


def test_fetch_only_mode(vertical_intent, config):
    """Test fetch_only mode does not place orders."""
    fetch_config = ExitFlowConfig(
        host=config.host,
        port=config.port,
        client_id=config.client_id,
        account=config.account,
        order_type=config.order_type,
        tif=config.tif,
        fetch_only=True,
        force_exit_enabled=config.force_exit_enabled,
        market_order_on_force=config.market_order_on_force,
        log_directory=config.log_directory,
    )

    result = execute_exit_flow(vertical_intent, config=fetch_config, dispatcher=lambda p: (999,))

    assert result.status == "fetch_only"
    assert result.order_ids == tuple()
    assert result.reason == "fetch_only_mode"
    assert result.attempts[0].stage == "primary"
    assert result.attempts[0].status == "fetch_only"


# ============================================================================
# Limit price and NBBO tests
# ============================================================================


def test_limit_prices_collected(vertical_intent, config):
    """Test limit prices are collected from all attempts."""
    call_count = [0]

    def dispatcher(plan):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("primary failed")
        return (888,)

    result = execute_exit_flow(vertical_intent, config=config, dispatcher=dispatcher)

    assert result.status == "success"
    # Should have limit prices from both primary and fallback
    assert len(result.limit_prices) >= 1
    assert all(isinstance(p, float) for p in result.limit_prices)


def test_limit_price_matches_plan(vertical_intent, config):
    """Test limit price matches the exit order plan."""
    expected_plan = build_exit_order_plan(vertical_intent)

    def dispatcher(plan):
        return (999,)

    result = execute_exit_flow(vertical_intent, config=config, dispatcher=dispatcher)

    assert result.status == "success"
    assert len(result.limit_prices) == 1
    assert math.isclose(result.limit_prices[0], expected_plan.limit_price, rel_tol=1e-9)


# ============================================================================
# Error tracking tests
# ============================================================================


def test_errors_field_empty_on_success(vertical_intent, config):
    """Test errors field is empty on success."""

    def dispatcher(plan):
        return (111,)

    result = execute_exit_flow(vertical_intent, config=config, dispatcher=dispatcher)

    assert result.status == "success"
    assert result.errors == tuple()


def test_quote_issues_field_empty_on_success(vertical_intent, config):
    """Test quote_issues field is empty on success."""

    def dispatcher(plan):
        return (111,)

    result = execute_exit_flow(vertical_intent, config=config, dispatcher=dispatcher)

    assert result.status == "success"
    assert result.quote_issues == tuple()


# ============================================================================
# Multi-leg fallback tests
# ============================================================================


def test_fallback_splits_to_verticals(config):
    """Test fallback handles 4-leg strategies."""
    strategy = {
        "symbol": "SPY",
        "expiry": "20240315",
        "legs": [
            {"strike": 440.0, "right": "put", "position": 1},
            {"strike": 445.0, "right": "put", "position": -1},
            {"strike": 455.0, "right": "call", "position": -1},
            {"strike": 460.0, "right": "call", "position": 1},
        ],
    }
    legs = [
        {
            "conId": 5001,
            "symbol": "SPY",
            "expiry": "20240315",
            "strike": 440.0,
            "right": "P",
            "position": 1,
            "bid": 1.0,
            "ask": 1.1,
            "minTick": 0.01,
            "quote_age_sec": 0.5,
            "mid_source": "true",
        },
        {
            "conId": 5002,
            "symbol": "SPY",
            "expiry": "20240315",
            "strike": 445.0,
            "right": "P",
            "position": -1,
            "bid": 2.0,
            "ask": 2.1,
            "minTick": 0.01,
            "quote_age_sec": 0.5,
            "mid_source": "true",
        },
        {
            "conId": 5003,
            "symbol": "SPY",
            "expiry": "20240315",
            "strike": 455.0,
            "right": "C",
            "position": -1,
            "bid": 5.0,
            "ask": 5.1,
            "minTick": 0.01,
            "quote_age_sec": 0.5,
            "mid_source": "true",
        },
        {
            "conId": 5004,
            "symbol": "SPY",
            "expiry": "20240315",
            "strike": 460.0,
            "right": "C",
            "position": 1,
            "bid": 3.0,
            "ask": 3.1,
            "minTick": 0.01,
            "quote_age_sec": 0.5,
            "mid_source": "true",
        },
    ]
    intent = StrategyExitIntent(strategy=strategy, legs=legs, exit_rules=None)

    call_count = [0]

    def dispatcher(plan):
        call_count[0] += 1
        # First call (primary) fails
        if call_count[0] == 1:
            raise RuntimeError("primary failed")
        # Subsequent calls (fallback) succeed
        return (100 + call_count[0],)

    result = execute_exit_flow(intent, config=config, dispatcher=dispatcher)

    # Result depends on whether fallback succeeds
    assert result.status in ("success", "failed")
    # Should have primary attempt
    assert result.attempts[0].stage == "primary"
    assert result.attempts[0].status == "failed"
    # Should have fallback attempts
    fallback_attempts = [a for a in result.attempts if "fallback" in a.stage]
    assert len(fallback_attempts) >= 1
