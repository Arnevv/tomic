import warnings

from tomic.strategies import atm_iron_butterfly


chain = [
    {"expiry": "20250101", "strike": 100, "type": "C", "bid": 1.0, "ask": 1.2, "delta": 0.4, "edge": 0.1, "model": 1.0},
    {"expiry": "20250101", "strike": 100, "type": "P", "bid": 1.0, "ask": 1.2, "delta": -0.4, "edge": 0.1, "model": 1.0},
    {"expiry": "20250101", "strike": 105, "type": "C", "bid": 0.5, "ask": 0.7, "delta": 0.2, "edge": 0.1, "model": 1.0},
    {"expiry": "20250101", "strike": 95, "type": "P", "bid": 0.5, "ask": 0.7, "delta": -0.2, "edge": 0.1, "model": 1.0},
]


def test_wing_width_deprecation():
    cfg = {
        "strategies": {
            "atm_iron_butterfly": {
                "strike_to_strategy_config": {
                    "center_strike_relative_to_spot": [0],
                    "wing_width": 5,
                    "use_ATR": False,
                }
            }
        }
    }
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        props, _ = atm_iron_butterfly.generate("AAA", chain, cfg, 100.0, 1.0)
        assert isinstance(props, list)
        assert any("wing_width" in str(warn.message) for warn in w)
