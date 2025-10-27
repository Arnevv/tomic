import math
import pytest

from tomic.core.data import InterestRateProvider, InterestRateQuote
from tomic.core.pricing import MidService


class FixedRateProvider(InterestRateProvider):
    def __init__(self, value: float, source: str = "fixture") -> None:
        super().__init__(default_source=source)
        self._value = float(value)
        self._source = source

    def current(self, *, override: float | None = None, source: str | None = None) -> InterestRateQuote:  # type: ignore[override]
        if override is not None:
            return InterestRateQuote(value=float(override), source=source or "override")
        return InterestRateQuote(value=self._value, source=self._source)


def _option(expiry: str, strike: float, opt_type: str, **extra):
    payload = {
        "expiry": expiry,
        "strike": strike,
        "type": opt_type,
        "symbol": "AAA",
        "underlying": "AAA",
    }
    payload.update(extra)
    return payload


@pytest.fixture
def pricing_context(monkeypatch):
    monkeypatch.setenv("TOMIC_TODAY", "2024-06-01")
    chain = [
        _option("2024-06-21", 100, "call", bid=1.0, ask=1.2, spot=100.0),
        _option("2024-06-21", 100, "put"),
        _option("2024-06-21", 110, "call", close=0.9, spot=100.0),
        _option("2024-06-21", 110, "put"),
        _option("2024-06-21", 105, "call", modelprice=0.75, spot=100.0),
        _option("2024-06-21", 95, "put", close=0.5, spot=100.0),
    ]
    service = MidService(interest_provider=FixedRateProvider(0.01))
    context = service.build_context(chain, spot_price=100.0)
    return context, chain


def test_mid_service_fallback_matrix(pricing_context):
    context, chain = pricing_context
    quotes = {}
    for leg in chain:
        key = (leg["strike"], leg["type"])
        quotes[key] = context.quote_for(leg)

    call_true = quotes[(100, "call")]
    assert math.isclose(call_true.mid or 0.0, 1.1, rel_tol=1e-6)
    assert call_true.mid_source == "true"
    assert call_true.spread_flag == "abs"
    assert math.isclose(call_true.interest_rate or 0.0, 0.01, rel_tol=1e-6)
    assert call_true.interest_rate_source == "fixture"

    put_parity = quotes[(100, "put")]
    expected_put_mid = round(1.1 - 100 + 100 * math.exp(-0.01 * (20 / 365)), 4)
    assert math.isclose(put_parity.mid or 0.0, expected_put_mid, rel_tol=1e-6)
    assert put_parity.mid_source == "parity_true"
    assert put_parity.mid_fallback == "parity_true"
    assert put_parity.spread_flag == "missing"
    assert math.isclose(put_parity.interest_rate or 0.0, 0.01, rel_tol=1e-6)

    put_parity_close = quotes[(110, "put")]
    base_close = 0.9
    expected_parity_close = round(base_close - 100 + 110 * math.exp(-0.01 * (20 / 365)), 4)
    assert math.isclose(put_parity_close.mid or 0.0, expected_parity_close, rel_tol=1e-6)
    assert put_parity_close.mid_source == "parity_close"
    assert put_parity_close.mid_fallback == "parity_close"
    assert put_parity_close.spread_flag == "missing"

    call_model = quotes[(105, "call")]
    assert math.isclose(call_model.mid or 0.0, 0.75, rel_tol=1e-6)
    assert call_model.mid_source == "model"
    assert call_model.mid_fallback == "model"

    put_close = quotes[(95, "put")]
    assert math.isclose(put_close.mid or 0.0, 0.5, rel_tol=1e-6)
    assert put_close.mid_source == "close"
    assert put_close.mid_fallback == "close"
