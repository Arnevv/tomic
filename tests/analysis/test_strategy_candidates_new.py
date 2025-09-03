import pytest
from tomic.strategies import iron_condor
from tomic.strategy_candidates import _metrics
from tomic.utils import get_leg_right


def test_generate_strategy_candidates_requires_spot():
    chain = [{"expiry": "20250101", "strike": 100, "type": "C", "bid": 1, "ask": 1.2}]
    with pytest.raises(ValueError):
        iron_condor.generate("AAA", chain, {}, None, 1.0)


def test_generate_strategy_candidates_with_strings():
    chain = [
        {
            "expiry": "20250101",
            "strike": "110",
            "type": "C",
            "bid": "1",
            "ask": "1.2",
            "delta": "0.4",
            "edge": "0.1",
            "model": "0",
            "iv": "0.2",
        },
        {
            "expiry": "20250101",
            "strike": "120",
            "type": "C",
            "bid": "0.5",
            "ask": "0.7",
            "delta": "0.2",
            "edge": "0.1",
            "model": "0",
            "iv": "0.2",
        },
        {
            "expiry": "20250101",
            "strike": "90",
            "type": "P",
            "bid": "1.0",
            "ask": "1.1",
            "delta": "-0.3",
            "edge": "0.1",
            "model": "0",
            "iv": "0.2",
        },
        {
            "expiry": "20250101",
            "strike": "80",
            "type": "P",
            "bid": "0.4",
            "ask": "0.6",
            "delta": "-0.1",
            "edge": "0.1",
            "model": "0",
            "iv": "0.2",
        },
    ]
    cfg = {
        "strike_to_strategy_config": {
            "short_call_delta_range": [0.35, 0.45],
            "short_put_delta_range": [-0.35, -0.25],
            "wing_sigma_multiple": 1.0,
            "use_ATR": False,
        }
    }
    props, _ = iron_condor.generate("AAA", chain, cfg, 100.0, 1.0)
    assert isinstance(props, list)
    if props:
        for leg in props[0].legs:
            assert isinstance(leg["strike"], float)
            assert isinstance(leg["bid"], float)
            assert isinstance(leg["ask"], float)
            assert leg.get("spot") == 100.0
            assert float(leg.get("iv", 0)) > 0


def test_generate_strategy_candidates_missing_metrics_reason():
    chain = [
        {"expiry": "20250101", "strike": 110, "type": "C", "bid": 0.5, "ask": 0.7},
        {"expiry": "20250101", "strike": 120, "type": "C", "bid": 2.0, "ask": 2.2},
        {"expiry": "20250101", "strike": 90, "type": "P", "bid": 0.6, "ask": 0.8},
        {"expiry": "20250101", "strike": 80, "type": "P", "bid": 1.5, "ask": 1.7},
    ]
    cfg = {
        "strike_to_strategy_config": {
            "short_call_delta_range": [0.35, 0.45],
            "short_put_delta_range": [-0.35, -0.25],
            "wing_sigma_multiple": 1.0,
            "use_ATR": False,
        }
    }
    props, reasons = iron_condor.generate("AAA", chain, cfg, 100.0, 1.0)
    assert not props
    assert reasons


def test_parity_mid_used_for_missing_bidask(monkeypatch):
    import pandas as pd
    if not hasattr(pd, "DataFrame") or isinstance(pd.DataFrame, type(object)):
        pytest.skip("pandas not available", allow_module_level=True)

    monkeypatch.setenv("TOMIC_TODAY", "2024-06-01")
    chain = [
        {
            "expiry": "2025-01-01",
            "strike": 110,
            "type": "C",
            "delta": 0.4,
            "edge": 0.1,
            "model": 0,
            "mid": None,
        },
        {
            "expiry": "2025-01-01",
            "strike": 110,
            "type": "P",
            "delta": -0.4,
            "edge": 0.1,
            "model": 0,
            "mid": 10.0,
        },
        {
            "expiry": "2025-01-01",
            "strike": 120,
            "type": "C",
            "delta": 0.2,
            "edge": 0.1,
            "model": 0,
            "mid": 1.0,
        },
        {
            "expiry": "2025-01-01",
            "strike": 90,
            "type": "P",
            "delta": -0.3,
            "edge": 0.1,
            "model": 0,
            "mid": 1.0,
        },
        {
            "expiry": "2025-01-01",
            "strike": 80,
            "type": "P",
            "delta": -0.1,
            "edge": 0.1,
            "model": 0,
            "mid": 0.5,
        },
    ]
    cfg = {
        "strike_to_strategy_config": {
            "short_call_delta_range": [0.35, 0.45],
            "short_put_delta_range": [-0.35, -0.25],
            "wing_sigma_multiple": 1.0,
            "use_ATR": False,
        }
    }
    props, _ = iron_condor.generate("AAA", chain, cfg, 100.0, 1.0)
    assert props
    sc_leg = next(
        (
            l
            for l in props[0].legs
            if l.get("position") < 0
            and get_leg_right(l) == "call"
            and float(l.get("strike")) == 110
        ),
        None,
    )
    assert sc_leg is not None
    assert sc_leg.get("mid_from_parity") is True
    assert sc_leg.get("mid") is not None
    assert sc_leg.get("mid_fallback") == "parity"


def test_generate_multiple_expiries(monkeypatch):
    monkeypatch.setenv("TOMIC_TODAY", "2024-06-01")
    chain = [
        {"expiry": "2025-01-01", "strike": 110, "type": "C", "bid": 1.0, "ask": 1.2, "delta": 0.4, "edge": 0.1, "model": 0, "iv": 0.2},
        {"expiry": "2025-01-01", "strike": 120, "type": "C", "bid": 0.5, "ask": 0.7, "delta": 0.2, "edge": 0.1, "model": 0, "iv": 0.2},
        {"expiry": "2025-01-01", "strike": 90, "type": "P", "bid": 1.0, "ask": 1.1, "delta": -0.3, "edge": 0.1, "model": 0, "iv": 0.2},
        {"expiry": "2025-01-01", "strike": 80, "type": "P", "bid": 0.4, "ask": 0.6, "delta": -0.1, "edge": 0.1, "model": 0, "iv": 0.2},
        {"expiry": "2025-02-01", "strike": 115, "type": "C", "bid": 1.1, "ask": 1.3, "delta": 0.4, "edge": 0.1, "model": 0, "iv": 0.2},
        {"expiry": "2025-02-01", "strike": 125, "type": "C", "bid": 0.6, "ask": 0.8, "delta": 0.2, "edge": 0.1, "model": 0, "iv": 0.2},
        {"expiry": "2025-02-01", "strike": 95, "type": "P", "bid": 1.2, "ask": 1.3, "delta": -0.3, "edge": 0.1, "model": 0, "iv": 0.2},
        {"expiry": "2025-02-01", "strike": 85, "type": "P", "bid": 0.5, "ask": 0.7, "delta": -0.1, "edge": 0.1, "model": 0, "iv": 0.2},
    ]
    cfg = {
        "strike_to_strategy_config": {
            "short_call_delta_range": [0.35, 0.45],
            "short_put_delta_range": [-0.35, -0.25],
            "wing_sigma_multiple": 1.0,
            "use_ATR": False,
            "dte_range": [200, 300],
        }
    }

    monkeypatch.setattr(iron_condor, "compute_dynamic_width", lambda *a, **k: 10)

    def fake_score(strategy, proposal, spot):
        exp = proposal.legs[0]["expiry"]
        proposal.pos = 1
        proposal.ev = 1
        proposal.ev_pct = 1
        proposal.rom = 1
        proposal.edge = 0.1
        proposal.credit = 100
        proposal.margin = 100
        proposal.max_profit = 100
        proposal.max_loss = -50
        proposal.breakevens = [0]
        proposal.score = 1 if exp == "2025-01-01" else 2
        proposal.profit_estimated = False
        proposal.scenario_info = None
        return proposal.score, []

    monkeypatch.setattr(iron_condor, "calculate_score", fake_score)

    props, _ = iron_condor.generate("AAA", chain, cfg, 100.0, 1.0)
    assert len(props) == 2
    assert [p.score for p in props] == [2, 1]


def test_metrics_black_scholes_fallback(monkeypatch):
    monkeypatch.setenv("TOMIC_TODAY", "2024-06-01")
    legs = [
        {
            "expiry": "2024-07-01",
            "strike": 66,
            "type": "C",
            "position": -1,
            "mid": 1.2,
            "iv": 0.25,
            "spot": 65,
            "volume": 100,
            "open_interest": 1000,
        },
        {
            "expiry": "2024-07-01",
            "strike": 68,
            "type": "C",
            "position": 2,
            "mid": 0.6,
            "iv": 0.24,
            "spot": 65,
            "volume": 100,
            "open_interest": 1000,
        },
    ]
    metrics, _ = _metrics("ratio_spread", legs)
    assert metrics is not None
    assert all(leg.get("model") is not None for leg in legs)
    assert all(leg.get("delta") is not None for leg in legs)
