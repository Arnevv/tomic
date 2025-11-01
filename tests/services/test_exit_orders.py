import pytest

from tomic.services.exit_orders import ExitOrderPlan, build_exit_order_plan
from tomic.services.trade_management_service import StrategyExitIntent


@pytest.fixture
def sample_intent_credit():
    strategy = {
        "symbol": "XYZ",
        "expiry": "20240119",
        "legs": [
            {"strike": 100.0, "right": "call", "position": -1},
            {"strike": 105.0, "right": "call", "position": 1},
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
    ]
    return StrategyExitIntent(strategy=strategy, legs=legs, exit_rules=None)


def test_build_exit_order_plan_credit(sample_intent_credit):
    plan = build_exit_order_plan(sample_intent_credit)
    assert isinstance(plan, ExitOrderPlan)
    assert plan.action == "BUY"
    assert plan.quantity == 1
    assert abs(plan.limit_price - 0.55) < 1e-9
    assert abs(plan.nbbo.bid - 0.45) < 1e-9
    assert abs(plan.nbbo.ask - 0.65) < 1e-9
    assert plan.tradeability.startswith("(spread=")
    assert abs(plan.per_combo_credit - 55.0) < 1e-9


def test_build_exit_order_plan_debit():
    strategy = {"symbol": "ABC", "expiry": "20240315"}
    legs = [
        {
            "conId": 2001,
            "symbol": "ABC",
            "expiry": "20240315",
            "strike": 95.0,
            "right": "P",
            "position": 1,
            "bid": 0.9,
            "ask": 1.1,
            "minTick": 0.05,
            "quote_age_sec": 0.5,
            "mid_source": "true",
        }
    ]
    intent = StrategyExitIntent(strategy=strategy, legs=legs, exit_rules=None)
    plan = build_exit_order_plan(intent)
    assert plan.action == "SELL"
    assert abs(plan.limit_price - 1.0) < 1e-9
    assert abs(plan.per_combo_credit + 100.0) < 1e-9
    assert abs(plan.nbbo.bid - 0.9) < 1e-9
    assert abs(plan.nbbo.ask - 1.1) < 1e-9


def test_build_exit_order_plan_requires_nbbo():
    strategy = {"symbol": "NOP", "expiry": "20240119"}
    legs = [
        {
            "conId": 3001,
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
    with pytest.raises(ValueError, match="geen quote"):
        build_exit_order_plan(intent)


def test_exit_order_plan_allows_configured_fallback(monkeypatch):
    from tomic.services import exit_orders

    strategy = {"symbol": "LMN", "expiry": "20240119"}
    legs = [
        {
            "conId": 4001,
            "symbol": "LMN",
            "expiry": "20240119",
            "strike": 150.0,
            "right": "C",
            "position": -1,
            "bid": 2.05,
            "ask": 2.15,
            "minTick": 0.01,
            "quote_age_sec": 1.0,
            "mid_source": "close",
        },
        {
            "conId": 4002,
            "symbol": "LMN",
            "expiry": "20240119",
            "strike": 155.0,
            "right": "C",
            "position": 1,
            "bid": 1.45,
            "ask": 1.55,
            "minTick": 0.01,
            "quote_age_sec": 1.0,
            "mid_source": "close",
        },
    ]
    intent = StrategyExitIntent(strategy=strategy, legs=legs, exit_rules=None)

    monkeypatch.setattr(
        exit_orders,
        "exit_spread_config",
        lambda: {"absolute": 0.30, "relative": 0.08, "max_quote_age": 5.0},
    )
    monkeypatch.setattr(
        exit_orders,
        "exit_fallback_config",
        lambda: {"allow_preview": True, "allowed_sources": {"close"}},
    )
    monkeypatch.setattr(exit_orders, "exit_force_exit_config", lambda: {"enabled": False})

    plan = build_exit_order_plan(intent)
    assert "fallback_leg1=close" in plan.tradeability


def test_exit_order_gate_uses_exit_spread_relative(monkeypatch):
    from tomic.services import exit_orders

    strategy = {"symbol": "GHI", "expiry": "20240119"}
    legs = [
        {
            "conId": 6001,
            "symbol": "GHI",
            "expiry": "20240119",
            "strike": 100.0,
            "right": "C",
            "position": -1,
            "bid": 1.05,
            "ask": 1.10,
            "minTick": 0.01,
            "quote_age_sec": 0.5,
            "mid_source": "true",
        },
        {
            "conId": 6002,
            "symbol": "GHI",
            "expiry": "20240119",
            "strike": 105.0,
            "right": "C",
            "position": 1,
            "bid": 0.50,
            "ask": 0.55,
            "minTick": 0.01,
            "quote_age_sec": 0.5,
            "mid_source": "true",
        },
    ]
    intent = StrategyExitIntent(strategy=strategy, legs=legs, exit_rules=None)

    monkeypatch.setattr(
        exit_orders,
        "exit_spread_config",
        lambda: {"absolute": 0.01, "relative": 0.25, "max_quote_age": 5.0},
    )
    monkeypatch.setattr(
        exit_orders,
        "exit_fallback_config",
        lambda: {"allow_preview": False, "allowed_sources": set()},
    )
    monkeypatch.setattr(exit_orders, "exit_force_exit_config", lambda: {"enabled": False})

    plan = build_exit_order_plan(intent)
    assert "(spread=0.10 ≤ 0.14)" in plan.tradeability


def test_exit_order_plan_force_exit_overrides_gate(monkeypatch):
    from tomic.services import exit_orders

    strategy = {"symbol": "PQR", "expiry": "20240119"}
    legs = [
        {
            "conId": 5001,
            "symbol": "PQR",
            "expiry": "20240119",
            "strike": 100.0,
            "right": "P",
            "position": -1,
            "bid": 1.05,
            "ask": 1.15,
            "minTick": 0.01,
            "quote_age_sec": 20.0,
            "mid_source": "true",
        },
        {
            "conId": 5002,
            "symbol": "PQR",
            "expiry": "20240119",
            "strike": 95.0,
            "right": "P",
            "position": 1,
            "bid": 0.55,
            "ask": 0.65,
            "minTick": 0.01,
            "quote_age_sec": 20.0,
            "mid_source": "true",
        },
    ]
    intent = StrategyExitIntent(strategy=strategy, legs=legs, exit_rules=None)

    monkeypatch.setattr(
        exit_orders,
        "exit_spread_config",
        lambda: {"absolute": 0.30, "relative": 0.08, "max_quote_age": 5.0},
    )
    monkeypatch.setattr(
        exit_orders,
        "exit_fallback_config",
        lambda: {"allow_preview": False, "allowed_sources": set()},
    )

    monkeypatch.setattr(exit_orders, "exit_force_exit_config", lambda: {"enabled": False})
    with pytest.raises(ValueError, match="stale_quote_leg1"):
        build_exit_order_plan(intent)

    monkeypatch.setattr(exit_orders, "exit_force_exit_config", lambda: {"enabled": True})
    plan = build_exit_order_plan(intent)
    assert plan.tradeability.startswith("forced_exit:")
