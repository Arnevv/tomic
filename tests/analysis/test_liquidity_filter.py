from tomic.strategy_candidates import _metrics


def test_metrics_rejects_low_liquidity(monkeypatch):
    legs = [
        {
            "expiry": "20250101",
            "type": "P",
            "strike": 100,
            "delta": -0.4,
            "bid": 1.0,
            "ask": 1.2,
            "mid": 1.1,
            "edge": 0,
            "model": 1,
            "position": -1,
            "volume": 0,
            "open_interest": 0,
        },
        {
            "expiry": "20250101",
            "type": "P",
            "strike": 90,
            "delta": -0.2,
            "bid": 0.5,
            "ask": 0.7,
            "mid": 0.6,
            "edge": 0,
            "model": 1,
            "position": 1,
            "volume": 0,
            "open_interest": 0,
        },
    ]

    def fake_cfg_get(key, default=None):
        if key == "MIN_OPTION_VOLUME":
            return 10
        if key == "MIN_OPTION_OPEN_INTEREST":
            return 10
        return default

    monkeypatch.setattr("tomic.strategy_candidates.cfg_get", fake_cfg_get)
    metrics, reasons = _metrics("bull put spread", legs)
    assert metrics is None
    assert any("volume" in r for r in reasons)
