import pytest
from tomic.strategies import iron_condor


def _chain():
    return [
        {
            "expiry": "2025-01-01",
            "strike": 110,
            "type": "C",
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
            "type": "C",
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
            "type": "P",
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
            "type": "P",
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

    def fake_metrics(strategy, legs, spot):
        return {"pos": 50, "max_profit": 100, "max_loss": -50, "ev": 0.1, "score": 1}, []

    logs = []

    def fake_log(strategy, desc, metrics, result, reason, extra=None):
        logs.append((strategy, desc, result, reason))

    monkeypatch.setattr(iron_condor, "_metrics", fake_metrics)
    monkeypatch.setattr(iron_condor, "log_combo_evaluation", fake_log)

    iron_condor.generate("AAA", chain, cfg, 100.0, 1.0)
    assert any(
        l[1] == "SC 110.0 SP 90.0 σ 0.6" and l[2] == "pass" for l in logs
    )

    chain_fail = [c for c in chain if c["type"] == "C"]
    iron_condor.generate("AAA", chain_fail, cfg, 100.0, 1.0)
    assert any(
        l[1] == "delta scan" and l[2] == "reject" and "short optie ontbreekt" in l[3]
        for l in logs
    )
