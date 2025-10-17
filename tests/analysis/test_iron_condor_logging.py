from types import SimpleNamespace
from tomic.strategies import (
    iron_condor,
    atm_iron_butterfly,
    short_call_spread,
    short_put_spread,
    ratio_spread,
    backspread_put,
    calendar,
)
from tomic import logutils


def _chain():
    return [
        {
            "expiry": "2025-01-01",
            "strike": 110,
            "type": "call",
            "bid": 1.0,
            "ask": 1.2,
            "delta": 0.4,
            "edge": 0.1,
            "model": 0.1,
            "iv": 0.2,
        },
        {
            "expiry": "2025-01-01",
            "strike": 120,
            "type": "call",
            "bid": 0.5,
            "ask": 0.7,
            "delta": 0.2,
            "edge": 0.1,
            "model": 0.1,
            "iv": 0.2,
        },
        {
            "expiry": "2025-01-01",
            "strike": 90,
            "type": "put",
            "bid": 1.0,
            "ask": 1.1,
            "delta": -0.3,
            "edge": 0.1,
            "model": 0.1,
            "iv": 0.2,
        },
        {
            "expiry": "2025-01-01",
            "strike": 80,
            "type": "put",
            "bid": 0.4,
            "ask": 0.6,
            "delta": -0.1,
            "edge": 0.1,
            "model": 0.1,
            "iv": 0.2,
        },
    ]


def test_iron_condor_logging(monkeypatch):
    monkeypatch.setenv("TOMIC_TODAY", "2024-06-01")
    cfg = {
        "strike_to_strategy_config": {
            "short_call_delta_range": [0.35, 0.45],
            "short_put_delta_range": [-0.35, -0.25],
            "wing_sigma_multiple": 0.6,
            "use_ATR": False,
        }
    }
    chain = _chain()

    def fake_score(strategy, proposal, spot, **_):
        proposal.pos = 50
        proposal.max_profit = 100
        proposal.max_loss = -50
        proposal.ev = 0.1
        proposal.score = 1
        return 1, []

    messages: list[str] = []
    monkeypatch.setattr(iron_condor, "calculate_score", fake_score)
    capture_logger = SimpleNamespace(info=lambda m: messages.append(m))
    monkeypatch.setattr(logutils, "logger", capture_logger)
    monkeypatch.setattr("tomic.strategies.utils.logger", capture_logger)

    iron_condor.generate("AAA", chain, cfg, 100.0, 1.0)
    joined = " ".join(messages)
    assert "expiry=2025-01-01" in joined
    assert "SC=110.0C" in joined and "LC=120.0C" in joined
    assert "SP=90.0P" in joined and "LP=80.0P" in joined
    assert any("short legs: parity ok; long legs: fallback permitted (max 2)" in m for m in messages)

    messages.clear()
    chain_fail = [c for c in chain if c["type"] == "call"]
    iron_condor.generate("AAA", chain_fail, cfg, 100.0, 1.0)
    assert any("short optie ontbreekt" in m and "expiry=2025-01-01" in m for m in messages)


def test_other_strategies_log_policies(monkeypatch):
    monkeypatch.setenv("TOMIC_TODAY", "2024-06-01")
    chain = _chain()
    messages: list[str] = []
    capture_logger = SimpleNamespace(info=lambda m: messages.append(m))
    monkeypatch.setattr(logutils, "logger", capture_logger)
    monkeypatch.setattr("tomic.strategies.utils.logger", capture_logger)
    monkeypatch.setattr("tomic.strategies.calendar.logger", capture_logger)

    atm_cfg = {
        "strike_to_strategy_config": {
            "center_strike_relative_to_spot": [0],
            "wing_sigma_multiple": 0.6,
        }
    }
    atm_iron_butterfly.generate("AAA", chain, atm_cfg, 100.0, 1.0)
    assert any(
        "[atm_iron_butterfly] short legs: parity ok; long legs: fallback permitted (max 2)"
        in m
        for m in messages
    )

    messages.clear()
    sc_cfg = {
        "strike_to_strategy_config": {
            "short_call_delta_range": [0.2, 0.4],
            "long_leg_distance_points": 5,
        }
    }
    short_call_spread.generate("AAA", chain, sc_cfg, 100.0, 1.0)
    assert any("[short_call_spread] short=market/parity, long=fallback ok" in m for m in messages)

    messages.clear()
    sp_cfg = {
        "strike_to_strategy_config": {
            "short_put_delta_range": [-0.4, -0.2],
            "long_leg_distance_points": 5,
        }
    }
    short_put_spread.generate("AAA", chain, sp_cfg, 100.0, 1.0)
    assert any("[short_put_spread] short=market/parity, long=fallback ok" in m for m in messages)

    messages.clear()
    ratio_cfg = {
        "strike_to_strategy_config": {
            "short_leg_delta_range": [0.2, 0.4],
            "long_leg_distance_points": 5,
        }
    }
    ratio_spread.generate("AAA", chain, ratio_cfg, 100.0, 1.0)
    assert any(
        "[ratio_spread] short legs: parity ok; long legs: fallback permitted (max 2)"
        in m
        for m in messages
    )

    messages.clear()
    backspread_cfg = {
        "strike_to_strategy_config": {
            "short_put_delta_range": [0.1, 0.3],
            "long_leg_distance_points": 5,
        }
    }
    backspread_put.generate("AAA", chain, backspread_cfg, 100.0, 1.0)
    assert any(
        "[backspread_put] short legs: parity ok; long legs: fallback permitted (max 2)"
        in m
        for m in messages
    )

    messages.clear()
    cal_cfg = {
        "strike_to_strategy_config": {
            "base_strikes_relative_to_spot": [0],
            "expiry_gap_min_days": 0,
        }
    }
    calendar.generate("AAA", chain, cal_cfg, 100.0, 1.0)
    assert any("calendar: short parity ok, long fallback allowed (1)" in m for m in messages)
