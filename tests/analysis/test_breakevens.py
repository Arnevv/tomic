import tomic.strategy_candidates as sc


def test_breakevens_bull_put_spread():
    legs = [
        {"type": "P", "strike": 50, "position": -1},
        {"type": "P", "strike": 45, "position": 1},
    ]
    assert sc._breakevens("bull put spread", legs, 100) == [49.0]


def test_breakevens_short_call_spread():
    legs = [
        {"type": "C", "strike": 50, "position": -1},
        {"type": "C", "strike": 55, "position": 1},
    ]
    assert sc._breakevens("short_call_spread", legs, 150) == [51.5]


def test_breakevens_iron_condor():
    legs = [
        {"type": "P", "strike": 95, "position": -1},
        {"type": "P", "strike": 90, "position": 1},
        {"type": "C", "strike": 105, "position": -1},
        {"type": "C", "strike": 110, "position": 1},
    ]
    assert sc._breakevens("iron_condor", legs, 200) == [93.0, 107.0]

