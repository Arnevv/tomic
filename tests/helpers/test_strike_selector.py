import importlib
from unittest.mock import Mock

from tomic import strike_selector as ss


# Helper to reload module with provided config

def _reload_with(monkeypatch, conf=None):
    importlib.reload(ss)
    if conf is None:
        monkeypatch.setattr(ss, "cfg_get", lambda name, default=None: default)
    else:
        monkeypatch.setattr(ss, "cfg_get", lambda name, default=None: conf.get(name, default))
    return ss.StrikeSelector()


def _make_option(**attrs):
    mock = Mock()
    for key, value in attrs.items():
        setattr(mock, key, value)
    data = {
        "delta": getattr(mock, "delta", None),
        "strike": getattr(mock, "strike", None),
        "model_price": getattr(mock, "model_price", None),
        "margin": getattr(mock, "margin_requirement", None),
        "pos": getattr(mock, "probability_of_success", None),
    }
    data.update(attrs)
    return data


def test_default_config_used_if_strategy_missing(monkeypatch):
    selector = _reload_with(monkeypatch)
    assert selector.config == ss.FilterConfig()


def test_filter_by_delta_range(monkeypatch):
    conf = {"DELTA_MIN": -0.4, "DELTA_MAX": 0.4}
    selector = _reload_with(monkeypatch, conf)
    opts = [
        _make_option(delta=-0.5, strike=90),
        _make_option(delta=-0.3, strike=95),
        _make_option(delta=0.0, strike=100),
        _make_option(delta=0.5, strike=105),
    ]
    res = selector.select(opts)
    strikes = [o["strike"] for o in res]
    assert strikes == [95, 100]


def test_filter_on_rom_and_edge(monkeypatch):
    conf = {"STRIKE_MIN_ROM": 5, "STRIKE_MIN_EDGE": 0.2}
    selector = _reload_with(monkeypatch, conf)
    opts = [
        _make_option(delta=0, strike=100, rom=10, edge=0.3),
        _make_option(delta=0, strike=105, rom=4, edge=0.3),
        _make_option(delta=0, strike=110, rom=10, edge=0.1),
        _make_option(delta=0, strike=115, rom=None, edge=None),
    ]
    res = selector.select(opts)
    strikes = [o["strike"] for o in res]
    assert strikes == [100, 115]


def test_rejects_outside_qualified_strikes(monkeypatch):
    conf = {
        "DELTA_MIN": -0.3,
        "DELTA_MAX": 0.3,
        "STRIKE_MIN_ROM": 10,
        "STRIKE_MIN_EDGE": 0.2,
        "STRIKE_MIN_POS": 60,
        "STRIKE_MIN_EV": 1,
        "STRIKE_SKEW_MIN": -0.1,
        "STRIKE_SKEW_MAX": 0.1,
        "STRIKE_TERM_MIN": -0.2,
        "STRIKE_TERM_MAX": 0.2,
    }
    selector = _reload_with(monkeypatch, conf)
    base = {
        "rom": 15,
        "edge": 0.3,
        "pos": 70,
        "ev": 2,
        "skew": 0,
        "term_slope": 0,
    }
    opts = [
        _make_option(delta=0.1, strike=100, **base),
        _make_option(delta=0.4, strike=101, **base),
        _make_option(delta=0.1, strike=102, rom=5, edge=0.3, pos=70, ev=2, skew=0, term_slope=0),
        _make_option(delta=0.1, strike=103, rom=15, edge=0.1, pos=70, ev=2, skew=0, term_slope=0),
        _make_option(delta=0.1, strike=104, rom=15, edge=0.3, pos=50, ev=2, skew=0, term_slope=0),
        _make_option(delta=0.1, strike=105, rom=15, edge=0.3, pos=70, ev=0, skew=0, term_slope=0),
        _make_option(delta=0.1, strike=106, rom=15, edge=0.3, pos=70, ev=2, skew=0.2, term_slope=0),
        _make_option(delta=0.1, strike=107, rom=15, edge=0.3, pos=70, ev=2, skew=0, term_slope=0.3),
    ]
    res = selector.select(opts)
    strikes = [o["strike"] for o in res]
    assert strikes == [100]


def test_ev_and_pos_thresholds(monkeypatch):
    conf = {"STRIKE_MIN_EV": 1, "STRIKE_MIN_POS": 70}
    selector = _reload_with(monkeypatch, conf)
    opts = [
        _make_option(delta=0, strike=100, ev=2, pos=75),
        _make_option(delta=0, strike=105, ev=0.5, pos=80),
        _make_option(delta=0, strike=110, ev=2, pos=65),
    ]
    res = selector.select(opts)
    strikes = [o["strike"] for o in res]
    assert strikes == [100]

