import pytest
from tomic.strategy_candidates import generate_strategy_candidates


def test_generate_strategy_candidates_requires_spot():
    chain = [{"expiry": "20250101", "strike": 100, "type": "C", "bid": 1, "ask": 1.2}]
    with pytest.raises(ValueError):
        generate_strategy_candidates("AAA", "iron_condor", chain, 1.0, {}, None)
