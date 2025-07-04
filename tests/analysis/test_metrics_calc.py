import math
from tomic.analysis.metrics import historical_volatility, average_true_range
from tomic.metrics import (
    calculate_edge,
    calculate_rom,
    calculate_pos,
    calculate_ev,
    calculate_margin,
)


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
        {"strike": 105, "type": "P", "action": "SELL"},
        {"strike": 100, "type": "P", "action": "BUY"},
    ]
    assert math.isclose(calculate_margin("bull put spread", legs, net_cashflow=1.2), 380.0)


def test_calculate_margin_calendar():
    legs = [
        {"strike": 100, "type": "C", "action": "BUY"},
        {"strike": 100, "type": "C", "action": "SELL"},
    ]
    assert math.isclose(
        calculate_margin("calendar", legs, net_cashflow=-2.5), 250.0
    )


def test_calculate_margin_ratio_backspread():
    legs = [
        {"strike": 105, "type": "P", "action": "SELL", "qty": 1},
        {"strike": 100, "type": "P", "action": "BUY", "qty": 2},
    ]
    assert math.isclose(
        calculate_margin("backspread_put", legs, net_cashflow=0.2), 0.0
    )
