import json
import math
from pathlib import Path

import pytest

from tomic.services.exit_flow import (
    ExitAttemptResult,
    ExitFlowConfig,
    execute_exit_flow,
    store_exit_flow_result,
)
from tomic.services import exit_orders
from tomic.services.exit_orders import build_exit_order_plan
from tomic.services.trade_management_service import StrategyExitIntent


@pytest.fixture
def sample_intent() -> StrategyExitIntent:
    strategy = {
        "symbol": "XYZ",
        "expiry": "20240119",
        "legs": [
            {"strike": 100.0, "right": "call", "position": -1},
            {"strike": 105.0, "right": "call", "position": 1},
            {"strike": 95.0, "right": "put", "position": -1},
            {"strike": 90.0, "right": "put", "position": 1},
        ],
    }
    legs = [
        {
            "conId": 1001,
            "symbol": "XYZ",
            "expiry": "20240119",
            "strike": 100.0,
            "right": "C",
            "position": -1,
            "bid": 1.1,
            "ask": 1.2,
            "minTick": 0.01,
            "quote_age_sec": 0.5,
            "mid_source": "true",
        },
        {
            "conId": 1002,
            "symbol": "XYZ",
            "expiry": "20240119",
            "strike": 105.0,
            "right": "C",
            "position": 1,
            "bid": 0.55,
            "ask": 0.65,
            "minTick": 0.01,
            "quote_age_sec": 0.5,
            "mid_source": "true",
        },
        {
            "conId": 1003,
            "symbol": "XYZ",
            "expiry": "20240119",
            "strike": 95.0,
            "right": "P",
            "position": -1,
            "bid": 1.05,
            "ask": 1.2,
            "minTick": 0.01,
            "quote_age_sec": 0.5,
            "mid_source": "true",
        },
        {
            "conId": 1004,
            "symbol": "XYZ",
            "expiry": "20240119",
            "strike": 90.0,
            "right": "P",
            "position": 1,
            "bid": 0.35,
            "ask": 0.45,
            "minTick": 0.01,
            "quote_age_sec": 0.5,
            "mid_source": "true",
        },
    ]
    return StrategyExitIntent(strategy=strategy, legs=legs, exit_rules=None)


@pytest.fixture
def base_config(tmp_path: Path) -> ExitFlowConfig:
    return ExitFlowConfig(
        host="127.0.0.1",
        port=4002,
        client_id=42,
        account=None,
        order_type="LMT",
        tif="DAY",
        fetch_only=False,
        force_exit_enabled=False,
        market_order_on_force=False,
        log_directory=tmp_path,
    )


def test_execute_exit_flow_success(sample_intent, base_config):
    dispatch_calls = []

    def dispatcher(plan):
        dispatch_calls.append(plan.limit_price)
        return (777,)

    result = execute_exit_flow(sample_intent, config=base_config, dispatcher=dispatcher)
    expected_limit = build_exit_order_plan(sample_intent).limit_price
    assert result.status == "success"
    assert result.reason == "primary"
    assert result.order_ids == (777,)
    assert math.isclose(result.limit_prices[0], expected_limit)
    assert not result.forced
    assert result.attempts and result.attempts[0].status == "success"
    assert result.attempts[0].stage == "primary"
    assert math.isclose(result.attempts[0].limit_price or 0, expected_limit)
    assert dispatch_calls


def test_execute_exit_flow_fetch_only(sample_intent, base_config, monkeypatch):
    cfg = base_config
    cfg = ExitFlowConfig(
        host=cfg.host,
        port=cfg.port,
        client_id=cfg.client_id,
        account=cfg.account,
        order_type=cfg.order_type,
        tif=cfg.tif,
        fetch_only=True,
        force_exit_enabled=cfg.force_exit_enabled,
        market_order_on_force=cfg.market_order_on_force,
        log_directory=cfg.log_directory,
    )

    result = execute_exit_flow(sample_intent, config=cfg, dispatcher=lambda plan: (999,))
    assert result.status == "fetch_only"
    assert result.order_ids == tuple()
    assert result.reason == "fetch_only_mode"
    assert result.attempts == (
        ExitAttemptResult(
            stage="primary",
            status="fetch_only",
            limit_price=result.limit_prices[0],
            order_ids=tuple(),
            reason="fetch_only_mode",
        ),
    )


def test_execute_exit_flow_fallback_success(sample_intent, base_config):
    calls: list[str] = []

    def dispatcher(plan):
        if not calls:
            calls.append("primary")
            raise RuntimeError("main bag failed")
        wing = plan.legs[0].get("right")
        label = "call" if str(wing).lower().startswith("c") else "put"
        calls.append(label)
        return (100 if label == "call" else 200,)

    result = execute_exit_flow(sample_intent, config=base_config, dispatcher=dispatcher)
    assert result.status == "success"
    assert result.reason == "fallback:main_bag_failure"
    assert result.order_ids == (100, 200)
    assert len(result.limit_prices) == 3  # primary + two fallbacks
    stages = {attempt.stage: attempt.status for attempt in result.attempts}
    assert stages["primary"] == "failed"
    assert stages["fallback:call"] == "success"
    assert stages["fallback:put"] == "success"
    assert calls == ["primary", "call", "put"]


def test_execute_exit_flow_fallback_failure(sample_intent, base_config):
    calls: list[str] = []

    def dispatcher(plan):
        if not calls:
            calls.append("primary")
            raise RuntimeError("main bag failed")
        wing = plan.legs[0].get("right")
        label = "call" if str(wing).lower().startswith("c") else "put"
        calls.append(label)
        return tuple()

    result = execute_exit_flow(sample_intent, config=base_config, dispatcher=dispatcher)

    assert result.status == "failed"
    assert result.reason == "main bag failed"
    stages = {attempt.stage: attempt for attempt in result.attempts}
    assert stages["primary"].status == "failed"
    assert stages["fallback:call"].status == "failed"
    assert stages["fallback:call"].reason == "no_order_ids"
    assert stages["fallback:put"].status == "failed"
    assert stages["fallback:put"].reason == "no_order_ids"
    assert calls == ["primary", "call", "put"]


def test_execute_exit_flow_uses_price_ladder(monkeypatch, sample_intent, base_config):
    base_plan = build_exit_order_plan(sample_intent)
    base_limit = base_plan.limit_price

    def ladder_config():
        return {
            "enabled": True,
            "steps": [0.05],
            "step_wait_seconds": 0.0,
            "max_duration_seconds": 0.0,
        }

    monkeypatch.setattr("tomic.services.exit_flow.exit_price_ladder_config", ladder_config)

    dispatch_limits: list[float] = []

    def dispatcher(plan):
        dispatch_limits.append(plan.limit_price)
        if len(dispatch_limits) == 1:
            raise RuntimeError("primary failure")
        return (321,)

    result = execute_exit_flow(sample_intent, config=base_config, dispatcher=dispatcher)

    assert result.status == "success"
    assert result.reason == "ladder:1"
    assert result.order_ids == (321,)
    assert len(dispatch_limits) == 2
    assert math.isclose(dispatch_limits[0], base_limit)
    assert dispatch_limits[1] > dispatch_limits[0]


def test_price_ladder_respects_limit_cap(monkeypatch, sample_intent, base_config):
    base_plan = build_exit_order_plan(sample_intent)
    base_limit = base_plan.limit_price

    monkeypatch.setattr(
        "tomic.services.exit_flow.exit_price_ladder_config",
        lambda: {
            "enabled": True,
            "steps": [1.0],
            "step_wait_seconds": 0.0,
            "max_duration_seconds": 0.0,
        },
    )

    monkeypatch.setattr(
        "tomic.services.exit_flow.exit_force_exit_config",
        lambda: {
            "enabled": True,
            "market_order": False,
            "limit_cap": {"type": "absolute", "value": 0.02},
        },
    )

    dispatch_limits: list[float] = []

    def dispatcher(plan):
        dispatch_limits.append(plan.limit_price)
        if len(dispatch_limits) == 1:
            raise RuntimeError("primary failure")
        return (654,)

    result = execute_exit_flow(
        sample_intent,
        config=base_config,
        dispatcher=dispatcher,
        force_exit=True,
    )

    assert result.status == "success"
    assert result.reason == "ladder:1"
    assert len(dispatch_limits) == 2
    assert math.isclose(dispatch_limits[0], base_limit)
    assert math.isclose(dispatch_limits[1], base_limit + 0.02, rel_tol=1e-9)


def test_execute_exit_flow_plan_failure(base_config):
    strategy = {"symbol": "NOP", "expiry": "20240119"}
    legs = [
        {
            "conId": 9999,
            "symbol": "NOP",
            "expiry": "20240119",
            "strike": 50.0,
            "right": "C",
            "position": -1,
            "bid": None,
            "ask": 1.0,
            "minTick": 0.01,
        }
    ]
    intent = StrategyExitIntent(strategy=strategy, legs=legs, exit_rules=None)
    result = execute_exit_flow(intent, config=base_config, dispatcher=lambda plan: (1,))
    assert result.status == "failed"
    assert "niet verhandelbaar" in result.reason.lower()
    assert result.order_ids == tuple()
    assert result.limit_prices == tuple()


def test_exit_flow_config_from_app_config(monkeypatch, tmp_path):
    values = {
        "IB_HOST": "1.2.3.4",
        "IB_PAPER_MODE": True,
        "IB_PORT": 5555,
        "IB_ORDER_CLIENT_ID": 88,
        "IB_CLIENT_ID": 77,
        "IB_ACCOUNT_ALIAS": "DU123",
        "DEFAULT_ORDER_TYPE": "lmt",
        "DEFAULT_TIME_IN_FORCE": "day",
        "IB_FETCH_ONLY": False,
        "EXPORT_DIR": str(tmp_path),
        "EXIT_ORDER_OPTIONS": {"force_exit": {"enabled": True, "market_order": True}},
    }

    def fake_get(key, default=None):
        return values.get(key, default)

    monkeypatch.setattr("tomic.config.get", fake_get)
    monkeypatch.setattr("tomic.services._config.cfg_get", fake_get)
    monkeypatch.setattr("tomic.services.exit_flow.cfg_get", fake_get)

    config = ExitFlowConfig.from_app_config()
    assert config.host == "1.2.3.4"
    assert config.port == 5555
    assert config.client_id == 88
    assert config.account == "DU123"
    assert config.order_type == "LMT"
    assert config.tif == "DAY"
    assert config.force_exit_enabled is True
    assert config.market_order_on_force is True
    assert config.order_type_for(True) == "MKT"
    assert config.order_type_for(False) == "LMT"
    assert config.log_directory == Path(tmp_path) / "exit_results"


def test_store_exit_flow_result(tmp_path, sample_intent, base_config):
    result = execute_exit_flow(sample_intent, config=base_config, dispatcher=lambda plan: (123,))
    path = store_exit_flow_result(sample_intent, result, directory=tmp_path)
    assert path.exists()
    payload = json.loads(path.read_text())
    assert payload["status"] == result.status
    assert payload["order_ids"] == list(result.order_ids)
    assert payload["limit_prices"] == list(result.limit_prices)
    assert payload["symbol"] == "XYZ"
    assert payload["attempts"]
@pytest.fixture(autouse=True)
def relaxed_exit_gate(monkeypatch):
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
        lambda: {"enabled": False, "market_order": False},
    )

