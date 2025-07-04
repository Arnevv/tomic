import datetime
from tomic.strategy_candidates import _find_option


def test_find_option_normalizes_fields():
    chain = [
        {"expiry": datetime.date(2025, 1, 1), "strike": 100, "type": "call"},
    ]
    opt = _find_option(chain, "2025-01-01", 100, "C")
    assert opt is chain[0]


def test_find_option_tolerance_float():
    chain = [
        {"expiry": "2025-01-01", "strike": 100.0, "type": "C"},
    ]
    opt = _find_option(chain, "2025-01-01", 100.005, "call")
    assert opt is chain[0]

