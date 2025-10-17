from contextlib import nullcontext

import pytest

from tomic.strategy_candidates import generate_strategy_candidates
from tomic import config
from tomic.strategies import iron_condor
@pytest.mark.parametrize(
    "cfg,expect_warn",
    [
        (
            {
                "strategies": {
                    "iron_condor": {
                        "strike_to_strategy_config": {
                            "short_call_delta_range": [0.35, 0.45],
                            "short_put_delta_range": [-0.35, -0.25],
                            "wing_sigma_multiple": 0.35,
                            "use_ATR": False,
                        }
                    }
                }
            },
            False,
        ),
        (
            {
                "strategies": {
                    "iron_condor": {
                        "strike_config": {
                            "short_call_multiplier": [0.35, 0.45],
                            "short_put_multiplier": [-0.35, -0.25],
                            "wing_width": 0.35,
                            "use_ATR": False,
                        }
                    }
                }
            },
            True,
        ),
    ],
)
def test_generate_candidates_uses_global_config(monkeypatch, cfg, expect_warn):
    monkeypatch.setenv("TOMIC_TODAY", "2024-06-01")
    chain = [
        {"expiry": "20250101", "strike": 110, "type": "C", "bid": 1.0, "ask": 1.2, "delta": 0.4, "edge": 0.1, "model": 0, "iv": 0.2},
        {"expiry": "20250101", "strike": 120, "type": "C", "bid": 0.5, "ask": 0.7, "delta": 0.2, "edge": 0.1, "model": 0, "iv": 0.2},
        {"expiry": "20250101", "strike": 90, "type": "P", "bid": 1.0, "ask": 1.1, "delta": -0.3, "edge": 0.1, "model": 0, "iv": 0.2},
        {"expiry": "20250101", "strike": 80, "type": "P", "bid": 0.4, "ask": 0.6, "delta": -0.1, "edge": 0.1, "model": 0, "iv": 0.2},
    ]
    monkeypatch.setattr(config, "STRATEGY_CONFIG", cfg)
    def fake_score(strategy, proposal, spot, **_):
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
        proposal.score = 1
        proposal.profit_estimated = False
        proposal.scenario_info = None
        return 1, []

    monkeypatch.setattr(iron_condor, "calculate_score", fake_score)
    ctx = pytest.warns(DeprecationWarning) if expect_warn else nullcontext()
    with ctx:
        proposals, reasons = generate_strategy_candidates(
            "AAA", "iron_condor", chain, 1.0, None, 100.0
        )
    assert "ontbrekende strikes" in [reason.message for reason in reasons]
    assert isinstance(proposals, list)
