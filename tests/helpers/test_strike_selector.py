import importlib
from unittest.mock import Mock

import pytest

from tomic import strike_selector as ss
from tomic.criteria import load_criteria


# Helper to reload module with provided config

def _reload_with(monkeypatch, conf=None):
    importlib.reload(ss)
    base = load_criteria()
    if conf is None:
        criteria = base
    else:
        criteria = base.model_copy(
            update={"strike": base.strike.model_copy(update=conf)}
        )
    return ss.StrikeSelector(criteria=criteria)


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
    assert selector.config == ss.load_filter_config(load_criteria())


@pytest.mark.parametrize(
    "rules, expected_delta, expected_dte",
    [
        ({"delta_range": [-0.35, 0.2], "dte_range": [20, 45]}, (-0.35, 0.2), (20, 45)),
        (
            {"short_delta_range": [-0.30, -0.18], "dte_range": [25, 50]},
            (-0.30, -0.18),
            (25, 50),
        ),
        (
            {"short_delta_range": [0.15, 0.35], "dte_range": [30, 55]},
            (0.15, 0.35),
            (30, 55),
        ),
    ],
)
def test_load_filter_config_applies_rule_ranges(rules, expected_delta, expected_dte):
    base = load_criteria()
    cfg = ss.load_filter_config(base, rules)
    assert cfg.delta_range == expected_delta
    assert cfg.dte_range == expected_dte


def test_load_filter_config_defaults_to_criteria():
    base = load_criteria()
    cfg = ss.load_filter_config(base, {})
    assert cfg.delta_range == (base.strike.delta_min, base.strike.delta_max)
    assert cfg.dte_range == ss.DEFAULT_DTE_RANGE


def test_filter_by_delta_range(monkeypatch):
    conf = {"delta_min": -0.4, "delta_max": 0.4}
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
    conf = {"min_rom": 5, "min_edge": 0.2}
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
        "delta_min": -0.3,
        "delta_max": 0.3,
        "min_rom": 10,
        "min_edge": 0.2,
        "min_pos": 60,
        "min_ev": 1,
        "skew_min": -0.1,
        "skew_max": 0.1,
        "term_min": -0.2,
        "term_max": 0.2,
    }
    selector = _reload_with(monkeypatch, conf)
    base = {
        "rom": 15,
        "edge": 0.3,
        "pos": 70,
        "ev": 2,
        "skew": 0,
        "term_m1_m3": 0,
    }
    opts = [
        _make_option(delta=0.1, strike=100, **base),
        _make_option(delta=0.4, strike=101, **base),
        _make_option(delta=0.1, strike=102, rom=5, edge=0.3, pos=70, ev=2, skew=0, term_m1_m3=0),
        _make_option(delta=0.1, strike=103, rom=15, edge=0.1, pos=70, ev=2, skew=0, term_m1_m3=0),
        _make_option(delta=0.1, strike=104, rom=15, edge=0.3, pos=50, ev=2, skew=0, term_m1_m3=0),
        _make_option(delta=0.1, strike=105, rom=15, edge=0.3, pos=70, ev=0, skew=0, term_m1_m3=0),
        _make_option(delta=0.1, strike=106, rom=15, edge=0.3, pos=70, ev=2, skew=0.2, term_m1_m3=0),
        _make_option(delta=0.1, strike=107, rom=15, edge=0.3, pos=70, ev=2, skew=0, term_m1_m3=0.3),
    ]
    res = selector.select(opts)
    strikes = [o["strike"] for o in res]
    assert strikes == [100]


def test_ev_and_pos_thresholds(monkeypatch):
    conf = {"min_ev": 1, "min_pos": 70}
    selector = _reload_with(monkeypatch, conf)
    opts = [
        _make_option(delta=0, strike=100, ev=2, pos=75),
        _make_option(delta=0, strike=105, ev=0.5, pos=80),
        _make_option(delta=0, strike=110, ev=2, pos=65),
    ]
    res = selector.select(opts)
    strikes = [o["strike"] for o in res]
    assert strikes == [100]

