from tomic.strategy_candidates import _build_strike_map, _nearest_strike
from tomic.criteria import AlertCriteria, CriteriaConfig, load_criteria


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


def test_nearest_strike_uses_config():
    chain = [{"expiry": "20250101", "strike": 100, "type": "c"}]
    m = _build_strike_map(chain)
    base = load_criteria()
    criteria = CriteriaConfig(
        strike=base.strike,
        strategy=base.strategy,
        market_data=base.market_data,
        alerts=AlertCriteria(nearest_strike_tolerance_percent=5.0,
                             skew_threshold=base.alerts.skew_threshold,
                             iv_hv_min_spread=base.alerts.iv_hv_min_spread,
                             iv_rank_threshold=base.alerts.iv_rank_threshold),
        portfolio=base.portfolio,
    )
    res = _nearest_strike(m, "20250101", "c", 104, criteria=criteria)
    assert res.matched == 100
