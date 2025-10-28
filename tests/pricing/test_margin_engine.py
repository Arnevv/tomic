from __future__ import annotations

import math

from tomic.pricing.margin_engine import compute_margin_and_rr


def test_margin_engine_credit_spread():
    combination = {
        "strategy": "short_put_spread",
        "legs": [
            {"strike": 105, "type": "P", "position": -1},
            {"strike": 100, "type": "P", "position": 1},
        ],
        "net_cashflow": 1.2,
    }
    config = {"min_risk_reward": 0.3}
    result = compute_margin_and_rr(combination, config)

    assert math.isclose(result.margin or 0.0, 380.0)
    assert math.isclose(result.max_profit or 0.0, 120.0)
    assert math.isclose(result.max_loss or 0.0, -380.0)
    assert math.isclose(result.risk_reward or 0.0, 120.0 / 380.0)
    assert result.meets_min_risk_reward is True


def test_margin_engine_backspread_uses_margin_as_risk():
    combination = {
        "strategy": "backspread_put",
        "legs": [
            {"strike": 105, "type": "P", "position": -1},
            {"strike": 100, "type": "P", "position": 2},
        ],
        "net_cashflow": 0.2,
    }
    result = compute_margin_and_rr(combination, None)

    assert result.margin is not None
    assert math.isclose(result.max_loss or 0.0, -abs(result.margin))


def test_margin_engine_flags_missing_risk_reward():
    combination = {
        "strategy": "short_call_spread",
        "legs": [
            {"strike": 100, "type": "C", "position": -1},
            {"strike": 105, "type": "C", "position": 1},
        ],
        "margin": 400.0,
        "max_profit": 100.0,
        "max_loss": -400.0,
    }
    config = {"min_risk_reward": 0.5}
    result = compute_margin_and_rr(combination, config)

    assert math.isclose(result.risk_reward or 0.0, 0.25)
    assert result.meets_min_risk_reward is False

