from tomic.cli.strategy_dashboard import print_strategy


def test_print_strategy_spot_diff(capsys):
    strat = {
        "symbol": "XYZ",
        "type": "Test",
        "spot_current": 105.1234,
        "spot_open": 100.0,
        "delta": 0.0,
        "gamma": 0.0,
        "vega": 0.0,
        "theta": 0.0,
        "IV_Rank": 0.0,
        "IV_Percentile": 0.0,
    }
    print_strategy(strat)
    captured = capsys.readouterr().out
    assert "Huidige spot: 105.12 (+5.12%)" in captured

