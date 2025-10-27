from __future__ import annotations

import pytest

from tomic.services.ib_marketdata import _normalize_symbol


@pytest.mark.parametrize(
    "leg,expected",
    [
        ({"symbol": "aaa"}, "AAA"),
        ({"underlying": "  bbb  "}, "BBB"),
        ({"ticker": "ccc"}, "CCC"),
        ({"root": "ddd"}, "DDD"),
        ({"root_symbol": "eee"}, "EEE"),
    ],
)
def test_normalize_symbol_prefers_known_keys(leg, expected):
    assert _normalize_symbol(leg) == expected


def test_normalize_symbol_missing_symbol_raises():
    with pytest.raises(ValueError):
        _normalize_symbol({})
