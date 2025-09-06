from tomic.helpers.bs_utils import populate_model_delta
from tomic.helpers.analysis.scoring import build_leg


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


def test_build_leg_populates_model_delta():
    quote = {
        **_sample_leg(),
        "bid": 1.0,
        "ask": 1.2,
    }
    leg = build_leg(quote, "long")
    assert leg.get("model") and leg.get("delta")
