from __future__ import annotations

from decimal import Decimal

import pytest

from tomic.analysis.scoring import _parse_mid_value


@pytest.mark.parametrize(
    "value,expected",
    [
        (Decimal("12.5"), 12.5),
        (b"34.5", 34.5),
        ("40.1", 40.1),
        (0, 0.0),
    ],
)
def test_parse_mid_value_parses_numeric_inputs(value, expected):
    has_mid, parsed = _parse_mid_value(value)
    assert has_mid is True
    assert parsed == expected


@pytest.mark.parametrize(
    "value",
    [None, "", float("nan"), Decimal("NaN"), b""],
)
def test_parse_mid_value_rejects_invalid_numbers(value):
    has_mid, parsed = _parse_mid_value(value)
    assert has_mid is False
    assert parsed is None
