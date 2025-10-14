from __future__ import annotations

import math

import pytest

from tomic.models import OptionContract
from tomic.services.ib_marketdata import IBMarketDataService, QuoteSnapshotApp


def _make_leg() -> dict[str, object]:
    return {
        "symbol": "HD",
        "expiry": "2025-11-21",
        "strike": 385.0,
        "type": "call",
        "position": -1,
    }


def test_tick_option_computation_handles_none_values() -> None:
    app = QuoteSnapshotApp()
    req_id = app._next_id()
    app.register_request(req_id, snapshot=False)
    app._event(req_id)

    app.tickOptionComputation(
        req_id,
        0,
        math.nan,
        math.nan,
        math.nan,
        math.nan,
        math.nan,
        None,
        None,
        math.nan,
    )

    data = app._responses.get(req_id, {})
    assert "delta" not in data
    assert "vega" not in data
    assert app._event(req_id).is_set() is False


def test_tick_option_computation_finalizes_on_first_valid_greek() -> None:
    app = QuoteSnapshotApp()
    req_id = app._next_id()
    app.register_request(req_id, snapshot=False)
    event = app._event(req_id)

    app.tickOptionComputation(
        req_id,
        0,
        math.nan,
        0.42,
        math.nan,
        math.nan,
        math.nan,
        math.nan,
        math.nan,
        math.nan,
    )

    data = app._responses.get(req_id, {})
    assert math.isclose(data["delta"], 0.42)
    assert event.is_set()


def test_contract_enrichment_updates_missing_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    service = IBMarketDataService()
    app = QuoteSnapshotApp()
    leg = _make_leg()
    leg.pop("type")
    leg["right"] = "call"
    contract = service._build_contract(leg)

    enriched = OptionContract(
        symbol="HD",
        expiry="20251121",
        strike=385.0,
        right="C",
        exchange="SMART",
        currency="USD",
        multiplier="100",
        trading_class="HD",
        primary_exchange="NYSE",
        con_id=123456,
    )

    def fake_request(_contract: object, timeout: float) -> OptionContract | None:
        assert timeout >= 1.0
        return enriched

    monkeypatch.setattr(app, "request_contract_details", fake_request, raising=True)

    updated = service._maybe_enrich_contract(app, leg, contract, timeout=3.0)

    assert leg["tradingClass"] == "HD"
    assert leg["primaryExchange"] == "NYSE"
    assert leg["conId"] == 123456
    assert updated is not contract
