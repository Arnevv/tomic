from tomic.analysis.greeks import compute_portfolio_greeks, compute_greeks_by_symbol


def test_compute_portfolio_greeks_basic():
    positions = [
        {
            "delta": 0.5,
            "gamma": 0.1,
            "vega": 0.2,
            "theta": -0.05,
            "position": 2,
            "multiplier": 100,
        },
        {
            "delta": -0.3,
            "gamma": 0.0,
            "vega": 0.1,
            "theta": -0.01,
            "position": -1,
            "multiplier": 50,
        },
        {"position": 1},
    ]
    result = compute_portfolio_greeks(positions)
    assert result["Delta"] == 1.3
    assert result["Gamma"] == 20.0
    assert result["Vega"] == 35.0
    assert result["Theta"] == -9.5


def test_compute_greeks_by_symbol():
    positions = [
        {
            "symbol": "AAPL",
            "delta": 1,
            "gamma": 0.1,
            "vega": 0.2,
            "theta": -0.05,
            "position": 1,
            "multiplier": 100,
        },
        {
            "symbol": "AAPL",
            "delta": -0.5,
            "gamma": 0.0,
            "vega": 0.1,
            "theta": -0.01,
            "position": -1,
            "multiplier": 100,
        },
        {
            "symbol": "TSLA",
            "delta": 0.3,
            "gamma": 0.2,
            "vega": -0.2,
            "theta": 0.02,
            "position": 2,
            "multiplier": 50,
        },
    ]
    res = compute_greeks_by_symbol(positions)
    assert res["AAPL"]["Delta"] == 1.5
    assert res["TSLA"]["Vega"] == -20.0
    assert "TOTAL" in res
