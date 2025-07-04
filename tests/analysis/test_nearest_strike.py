from tomic.strategy_candidates import _build_strike_map, _nearest_strike


def test_nearest_strike_simple():
    chain = [
        {"expiry": "20250101", "strike": 135, "type": "C"},
        {"expiry": "20250101", "strike": 136, "type": "C"},
        {"expiry": "20250101", "strike": 130, "type": "P"},
        {"expiry": "20250101", "strike": 129.5, "type": "P"},
    ]
    m = _build_strike_map(chain)
    assert _nearest_strike(m, "20250101", "C", 135.71).matched == 136
    assert _nearest_strike(m, "20250101", "P", 129.6).matched == 129.5
    assert _nearest_strike(m, "20250101", "C", 135.0).matched == 135


def test_nearest_strike_tolerance():
    chain = [
        {"expiry": "20250101", "strike": 100, "type": "C"},
    ]
    m = _build_strike_map(chain)
    res = _nearest_strike(m, "20250101", "C", 110, tolerance_percent=5.0)
    assert res.matched is None
