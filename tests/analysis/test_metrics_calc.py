import math
import pytest
from tomic.analysis.metrics import historical_volatility, average_true_range
from tomic.metrics import (
    MidPriceResolver,
    calculate_edge,
    calculate_rom,
    calculate_pos,
    calculate_ev,
    calculate_credit,
    calculate_margin,
    calculate_payoff_at_spot,
    estimate_scenario_profit,
    get_signed_position,
    iter_leg_views,
)
from tomic.strategies import StrategyName


def test_historical_volatility_constant():
    closes = [100 * (1.01**i) for i in range(31)]
    assert math.isclose(historical_volatility(closes), 0.0, abs_tol=1e-10)


def test_average_true_range_simple():
    highs = [i + 1 for i in range(15)]
    lows = [i for i in range(15)]
    closes = [i + 0.5 for i in range(15)]
    result = average_true_range(highs, lows, closes)
    assert math.isclose(result, 1.5)


def test_calculate_edge():
    assert math.isclose(calculate_edge(1.5, 1.0), 0.5)


def test_calculate_rom():
    assert math.isclose(calculate_rom(200, 1000), 20.0)


def test_calculate_pos():
    assert math.isclose(calculate_pos(0.25), 75.0)
    assert math.isclose(calculate_pos(-0.4), 60.0)


def test_calculate_ev():
    result = calculate_ev(60.0, 200.0, -100.0)
    assert math.isclose(result, 80.0)


def test_calculate_margin_credit_spread():
    legs = [
        {"strike": 105, "type": "p", "action": "SELL"},
        {"strike": 100, "type": "Put", "action": "BUY"},
    ]
    assert math.isclose(
        calculate_margin(StrategyName.SHORT_PUT_SPREAD, legs, net_cashflow=1.2), 380.0
    )


def test_calculate_margin_credit_call_spread():
    legs = [
        {"strike": 95, "type": "C", "action": "SELL"},
        {"strike": 100, "type": "CALL", "action": "BUY"},
    ]
    assert math.isclose(
        calculate_margin(StrategyName.SHORT_CALL_SPREAD, legs, net_cashflow=1.1), 390.0
    )


def test_vertical_spread_invalid_structure():
    legs = [
        {"strike": 100, "type": "C", "action": "SELL"},
        {"strike": 95, "type": "P", "action": "BUY"},
    ]
    with pytest.raises(ValueError):
        calculate_margin(StrategyName.SHORT_CALL_SPREAD, legs)


def test_calculate_margin_calendar():
    legs = [
        {"strike": 100, "type": "c", "action": "BUY"},
        {"strike": 100, "type": "CALL", "action": "SELL"},
    ]
    assert math.isclose(
        calculate_margin(StrategyName.CALENDAR, legs, net_cashflow=-2.5), 250.0
    )


def test_calculate_margin_ratio_backspread():
    legs = [
        {"strike": 105, "type": "PUT", "action": "SELL", "qty": 1},
        {"strike": 100, "type": "p", "action": "BUY", "qty": 2},
    ]
    assert math.isclose(
        calculate_margin(StrategyName.BACKSPREAD_PUT, legs, net_cashflow=0.2), 480.0
    )


def test_calculate_credit_and_margin_condor():
    legs = [
        {"strike": 105, "type": "C", "action": "SELL", "mid": 2.07, "position": -1},
        {"strike": 110, "type": "C", "action": "BUY", "mid": 0.95, "position": 1},
        {"strike": 95, "type": "P", "action": "SELL", "mid": 2.07, "position": -1},
        {"strike": 90, "type": "P", "action": "BUY", "mid": 0.95, "position": 1},
    ]
    credit = calculate_credit(legs)
    assert math.isclose(credit, 224.0)
    margin = calculate_margin(StrategyName.IRON_CONDOR, legs, net_cashflow=credit / 100)
    assert math.isclose(margin, 276.0)


def test_get_signed_position_prefers_explicit_position():
    leg = {"position": "-2", "qty": "5", "action": "BUY"}
    assert math.isclose(get_signed_position(leg), -2.0)


def test_get_signed_position_from_qty_and_action():
    leg = {"qty": "3", "action": "SELL"}
    assert math.isclose(get_signed_position(leg), -3.0)


def test_calculate_credit_handles_qty_zero_and_missing_position():
    legs = [
        {"type": "call", "mid": 1.25, "qty": "2", "action": "SELL"},
        {"type": "call", "mid": 0.55, "quantity": "1", "action": "BUY"},
        {"type": "put", "mid": 0.0, "qty": 1, "action": "BUY"},
        {"type": "put", "mid": 1.5, "qty": 0, "action": "SELL"},
    ]
    credit = calculate_credit(legs)
    assert math.isclose(credit, (1.25 * 2 - 0.55) * 100)


def test_iter_leg_views_normalizes_sources():
    leg = {
        "type": "call",
        "strike": 100,
        "expiry": "20240119",
        "position": -1,
        "mid": 1.1,
        "mid_fallback": "Parity",
        "quote_age_sec": "5",
    }
    view = next(iter_leg_views([leg], price_resolver=MidPriceResolver()))
    assert view.mid_source == "parity_true"
    assert math.isclose(view.quote_age or 0.0, 5.0)


def test_calculate_payoff_at_spot_naked_put():
    legs = [{"strike": 100, "type": "P", "position": -1, "mid": 1.5}]
    assert math.isclose(calculate_payoff_at_spot(legs, 105), 150.0)
    assert math.isclose(calculate_payoff_at_spot(legs, 90), -850.0)


def test_calculate_payoff_at_spot_vertical_call():
    legs = [
        {"strike": 100, "type": "CALL", "position": 1, "mid": 2.5},
        {"strike": 105, "type": "C", "position": -1, "mid": 1.0},
    ]
    assert math.isclose(calculate_payoff_at_spot(legs, 95), -150.0)
    assert math.isclose(calculate_payoff_at_spot(legs, 108), 350.0)


def test_estimate_scenario_profit():
    legs = [
        {"strike": 105, "type": "C", "action": "SELL", "mid": 2.07, "position": -1},
        {"strike": 110, "type": "C", "action": "BUY", "mid": 0.95, "position": 1},
        {"strike": 95, "type": "P", "action": "SELL", "mid": 2.07, "position": -1},
        {"strike": 90, "type": "P", "action": "BUY", "mid": 0.95, "position": 1},
    ]
    results, msg = estimate_scenario_profit(legs, 100, StrategyName.IRON_CONDOR)
    assert msg is None
    assert results and len(results) == 1
    scen = results[0]
    assert scen["scenario_label"] == "Spot blijft tussen spreads"
    assert math.isclose(scen["scenario_spot"], 100.0)
    expected = calculate_payoff_at_spot(legs, 100)
    assert math.isclose(scen["pnl"], expected)
    assert scen["preferred_move"] == "flat"


def test_estimate_scenario_profit_missing():
    results, msg = estimate_scenario_profit([], 100, "unknown_strategy")
    assert results is None
    assert msg == "no scenario defined"
