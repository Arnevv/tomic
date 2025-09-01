import pytest
from pydantic import ValidationError

from tomic.strategy_candidates import generate_strategy_candidates


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
