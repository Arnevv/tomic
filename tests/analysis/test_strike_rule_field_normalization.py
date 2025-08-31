import pytest

from tomic import loader

CASES = {
    "calendar": (
        {"strike_distance": 0, "expiry_gap_min": 20},
        {"base_strikes_relative_to_spot": [0], "expiry_gap_min_days": 20},
    ),
    "ratio_spread": (
        {"short_delta_range": [0.3, 0.45]},
        {"short_leg_delta_range": [0.3, 0.45]},
    ),
    "naked_put": (
        {"short_delta_range": [-0.3, -0.25]},
        {"short_put_delta_range": [-0.3, -0.25]},
    ),
    "short_put_spread": (
        {"short_delta_range": [-0.35, -0.2]},
        {"short_put_delta_range": [-0.35, -0.2]},
    ),
    "backspread_put": (
        {"short_delta_range": [0.15, 0.3]},
        {"short_put_delta_range": [0.15, 0.3]},
    ),
    "short_call_spread": (
        {"short_delta_range": [0.2, 0.35]},
        {"short_call_delta_range": [0.2, 0.35]},
    ),
    "atm_iron_butterfly": (
        {"wing_width": 5},
        {"wing_width_points": [5]},
    ),
    "iron_condor": (
        {"wing_width": [5]},
        {"wing_width_points": [5]},
    ),
}


@pytest.mark.parametrize("strategy,legacy,expected", [
    (name, cfg[0], cfg[1]) for name, cfg in CASES.items()
])
def test_normalization(strategy, legacy, expected):
    rules = loader.load_strike_config(strategy, {strategy: legacy})
    assert rules == expected
