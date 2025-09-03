import pytest
from pydantic import ValidationError

from tomic.strategy_candidates import generate_strategy_candidates
from tomic.strategies.config_models import (
    IronCondorStrikeConfig,
    ShortPutSpreadStrikeConfig,
)


@pytest.mark.parametrize(
    "strategy,cfg",
    [
        ("naked_put", {"strike_to_strategy_config": {"unknown": 1}}),
        (
            "short_put_spread",
            {"strike_to_strategy_config": {"short_put_delta_range": "oops"}},
        ),
    ],
)
def test_invalid_strike_config(strategy, cfg, monkeypatch):
    """Config models should reject invalid fields or types."""
    monkeypatch.setenv("TOMIC_TODAY", "2024-06-01")
    with pytest.raises(ValidationError):
        generate_strategy_candidates("AAA", strategy, [], 1.0, cfg, 100.0)


def test_long_leg_distance_and_atr_are_mutually_exclusive():
    with pytest.raises(ValidationError):
        ShortPutSpreadStrikeConfig(
            short_put_delta_range=(0.1, 0.2),
            long_leg_distance_points=0.1,
            long_leg_atr_multiple=1.0,
        )


def test_short_leg_width_points_and_ratio_are_mutually_exclusive():
    with pytest.raises(ValidationError):
        IronCondorStrikeConfig(
            short_call_delta_range=(0.1, 0.2),
            short_put_delta_range=(-0.2, -0.1),
            short_leg_width_points=5,
            short_leg_width_ratio=0.5,
        )
