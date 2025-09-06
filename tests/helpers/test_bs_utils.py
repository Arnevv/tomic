import pytest

from tomic.helpers.bs_utils import populate_model_delta
from tomic.utils import build_leg


def _sample_leg():
    return {
        "type": "C",
        "strike": 100,
        "spot": 100,
        "iv": 0.2,
        "expiry": "20991231",
    }


def test_populate_model_delta_sets_fields():
    leg = _sample_leg()
    populate_model_delta(leg)
    assert leg.get("model") and leg.get("delta")


def test_build_leg_populates_missing_fields():
    quote = {
        **_sample_leg(),
        "bid": 1.0,
        "ask": 1.2,
    }
    leg = build_leg(quote, "long")
    assert leg.get("mid") == pytest.approx(1.1)
    assert leg.get("model") and leg.get("delta")
    assert leg.get("edge") == pytest.approx(leg["model"] - leg["mid"])


def test_build_leg_preserves_existing_fields():
    quote = {
        **_sample_leg(),
        "mid": 5.0,
        "model": 6.0,
        "delta": 0.5,
        "edge": 1.0,
    }
    leg = build_leg(quote, "short")
    assert leg["mid"] == 5.0
    assert leg["model"] == 6.0
    assert leg["delta"] == 0.5
    assert leg["edge"] == 1.0
