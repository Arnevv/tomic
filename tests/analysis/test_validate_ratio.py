import math
from tomic.strategy_candidates import _validate_ratio


def test_validate_ratio_accepts_single_long_with_quantity_two():
    legs = [
        {"expiry": "2025-08-01", "strike": 66.0, "type": "C", "position": -1},
        {"expiry": "2025-08-01", "strike": 68.0, "type": "C", "position": 2},
    ]
    assert _validate_ratio("ratio_spread", legs, 0.1)

