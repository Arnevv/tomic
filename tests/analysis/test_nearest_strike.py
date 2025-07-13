from tomic.strategy_candidates import _build_strike_map, _nearest_strike


def test_nearest_strike_simple():
    chain = [
        {"expiry": "20250101", "strike": 135, "type": "call"},
        {"expiry": "20250101", "strike": 136, "type": "c"},
        {"expiry": "20250101", "strike": 130, "type": "PUT"},
        {"expiry": "20250101", "strike": 129.5, "type": "p"},
    ]
    m = _build_strike_map(chain)
    assert _nearest_strike(m, "20250101", "c", 135.71).matched == 136
    assert _nearest_strike(m, "20250101", "PUT", 129.6).matched == 129.5
    assert _nearest_strike(m, "20250101", "CALL", 135.0).matched == 135


def test_nearest_strike_tolerance():
    chain = [
        {"expiry": "20250101", "strike": 100, "type": "Call"},
    ]
    m = _build_strike_map(chain)
    res = _nearest_strike(m, "20250101", "c", 110, tolerance_percent=5.0)
    assert res.matched is None


def test_nearest_strike_uses_config(monkeypatch):
    chain = [{"expiry": "20250101", "strike": 100, "type": "c"}]
    m = _build_strike_map(chain)

    def fake_cfg_get(key, default=None):
        if key == "NEAREST_STRIKE_TOLERANCE_PERCENT":
            return 5.0
        return default

    monkeypatch.setattr("tomic.strategy_candidates.cfg_get", fake_cfg_get)
    res = _nearest_strike(m, "20250101", "c", 104)
    assert res.matched == 100
