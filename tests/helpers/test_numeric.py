from datetime import date

import math

from tomic.helpers.dateutils import normalize_earnings_context, normalize_expiry_code
from tomic.helpers.numeric import safe_float


def test_safe_float_parses_european_number():
    assert math.isclose(safe_float("1.234,56") or 0.0, 1234.56, rel_tol=1e-9)


def test_safe_float_strips_percentage_symbols():
    assert math.isclose(safe_float(" 12,34 %") or 0.0, 12.34, rel_tol=1e-9)


def test_safe_float_returns_none_for_nan():
    assert safe_float(math.nan) is None


def test_normalize_expiry_code_handles_short_year():
    assert normalize_expiry_code("231215") == "20231215"


def test_normalize_earnings_context_calculates_days(monkeypatch):
    today = date(2024, 1, 1)

    def fake_today() -> date:
        return today

    earnings_date, days_until = normalize_earnings_context("2024-01-10", None, fake_today)
    assert earnings_date == date(2024, 1, 10)
    assert days_until == 9
