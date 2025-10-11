from types import SimpleNamespace
from tomic.strategies import iron_condor
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

    def fake_score(strategy, proposal, spot):
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
