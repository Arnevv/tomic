import pytest
from pydantic import ValidationError

from tomic.criteria import StrategyRules


def test_strategy_score_weights_must_sum_to_one():
    with pytest.raises(ValidationError):
        StrategyRules(
            score_weight_rom=0.6,
            score_weight_pos=0.3,
            score_weight_ev=0.2,
        )
