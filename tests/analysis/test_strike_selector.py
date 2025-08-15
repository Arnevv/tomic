from importlib import reload

from tomic import strike_selector as ss
from tomic.criteria import StrikeCriteria, load_criteria


def test_selector_filters(monkeypatch):
    base = load_criteria()
    criteria = base.model_copy(
        update={
            "strike": StrikeCriteria(
                delta_min=-0.5,
                delta_max=0.5,
                min_rom=10,
                min_edge=0.2,
                min_pos=60,
                min_ev=0,
                skew_min=-0.1,
                skew_max=0.1,
                term_min=-0.2,
                term_max=0.2,
            )
        }
    )
    selector = ss.StrikeSelector(criteria=criteria)
    opts = [
        {
            "expiry": "20250101",
            "strike": 100,
            "type": "Call",
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
            "type": "c",
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


def test_filter_by_expiry_single(monkeypatch):
    monkeypatch.setenv("TOMIC_TODAY", "2024-06-01")
    reload(ss)
    selector = ss.StrikeSelector()
    opts = [
        {"expiry": "20240614", "strike": 100, "type": "c", "delta": 0.0},
        {"expiry": "20240621", "strike": 105, "type": "CALL", "delta": 0.0},
        {"expiry": "20240719", "strike": 110, "type": "Call", "delta": 0.0},
    ]
    res = selector.select(opts, dte_range=(10, 20))
    expiries = {o["expiry"] for o in res}
    assert expiries == {"20240614", "20240621"}


def test_filter_by_expiry_multi(monkeypatch):
    monkeypatch.setenv("TOMIC_TODAY", "2024-06-01")
    reload(ss)
    selector = ss.StrikeSelector()
    opts = [
        {"expiry": "20240614", "strike": 100, "type": "c", "delta": 0.0},
        {"expiry": "20240621", "strike": 105, "type": "Call", "delta": 0.0},
        {"expiry": "20240712", "strike": 110, "type": "CALL", "delta": 0.0},
        {"expiry": "20240719", "strike": 115, "type": "call", "delta": 0.0},
    ]
    res = selector.select(opts, dte_range=(10, 60))
    expiries = sorted({o["expiry"] for o in res})
    assert expiries == ["20240614", "20240621", "20240712", "20240719"]


def test_filter_by_expiry_none(monkeypatch):
    monkeypatch.setenv("TOMIC_TODAY", "2024-06-01")
    reload(ss)
    selector = ss.StrikeSelector()
    opts = [
        {"expiry": "20240610", "strike": 100, "type": "Call"},
        {"expiry": "20240801", "strike": 105, "type": "c"},
    ]
    res = selector.select(opts, dte_range=(20, 40))
    assert res == []
