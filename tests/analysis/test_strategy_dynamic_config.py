from tomic.strategy_candidates import generate_strategy_candidates
from tomic import config
from tomic.strategies import iron_condor


def test_generate_candidates_uses_global_config(monkeypatch):
    monkeypatch.setenv("TOMIC_TODAY", "2024-06-01")
    chain = [
        {"expiry": "20250101", "strike": 110, "type": "C", "bid": 1.0, "ask": 1.2, "delta": 0.4, "edge": 0.1, "model": 0, "iv": 0.2},
        {"expiry": "20250101", "strike": 120, "type": "C", "bid": 0.5, "ask": 0.7, "delta": 0.2, "edge": 0.1, "model": 0, "iv": 0.2},
        {"expiry": "20250101", "strike": 90, "type": "P", "bid": 1.0, "ask": 1.1, "delta": -0.3, "edge": 0.1, "model": 0, "iv": 0.2},
        {"expiry": "20250101", "strike": 80, "type": "P", "bid": 0.4, "ask": 0.6, "delta": -0.1, "edge": 0.1, "model": 0, "iv": 0.2},
    ]
    monkeypatch.setattr(
        config,
        "STRATEGY_CONFIG",
        {
            "strategies": {
                "iron_condor": {
                    "strike_to_strategy_config": {
                        "short_call_multiplier": [10],
                        "short_put_multiplier": [10],
                        "wing_width": 10,
                        "use_ATR": False,
                    }
                }
            }
        },
    )
    monkeypatch.setattr(
        iron_condor,
        "_metrics",
        lambda *a, **k: (
            {
                "pos": 1,
                "ev": 1,
                "ev_pct": 1,
                "rom": 1,
                "edge": 0.1,
                "credit": 100,
                "margin": 100,
                "max_profit": 100,
                "max_loss": -50,
                "breakevens": [0],
                "score": 1,
                "profit_estimated": False,
                "scenario_info": None,
            },
            [],
        ),
    )
    proposals, reason = generate_strategy_candidates("AAA", "iron_condor", chain, 1.0, None, 100.0)
    assert reason is None
    assert isinstance(proposals, list)
    assert proposals
