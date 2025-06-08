import math
from tomic.analysis.metrics import historical_volatility, average_true_range


def test_historical_volatility_constant():
    closes = [100 * (1.01 ** i) for i in range(31)]
    assert math.isclose(historical_volatility(closes), 0.0, abs_tol=1e-10)


def test_average_true_range_simple():
    highs = [i + 1 for i in range(15)]
    lows = [i for i in range(15)]
    closes = [i + 0.5 for i in range(15)]
    result = average_true_range(highs, lows, closes)
    assert math.isclose(result, 1.5)
