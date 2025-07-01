from importlib import reload

from tomic import strike_selector as ss


def test_selector_filters(monkeypatch):
    conf = {
        "DELTA_MIN": -0.5,
        "DELTA_MAX": 0.5,
        "STRIKE_MIN_ROM": 10,
        "STRIKE_MIN_EDGE": 0.2,
        "STRIKE_MIN_POS": 60,
        "STRIKE_MIN_EV": 0,
        "STRIKE_SKEW_MIN": -0.1,
        "STRIKE_SKEW_MAX": 0.1,
        "STRIKE_TERM_MIN": -0.2,
        "STRIKE_TERM_MAX": 0.2,
    }
    monkeypatch.setattr(ss, "cfg_get", lambda name, default=None: conf.get(name, default))
    reload(ss)
    selector = ss.StrikeSelector()
    opts = [
        {
            "expiry": "20250101",
            "strike": 100,
            "type": "C",
            "delta": 0.4,
            "rom": 15,
            "edge": 0.3,
            "pos": 70,
            "ev": 2,
            "skew": 0.05,
            "term_slope": 0.1,
            "gamma": 0.1,
            "vega": 0.2,
            "theta": -0.05,
        },
        {
            "expiry": "20250101",
            "strike": 110,
            "type": "C",
            "delta": 0.7,
            "rom": 20,
            "edge": 0.1,
            "pos": 80,
            "ev": -1,
            "skew": 0.05,
            "term_slope": 0.1,
            "gamma": 0.2,
            "vega": 0.2,
            "theta": -0.05,
        },
    ]
    result = selector.select(opts)
    assert len(result) == 1
    assert result[0]["strike"] == 100
