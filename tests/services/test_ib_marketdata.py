from __future__ import annotations

import math

import pytest

from tomic.services.ib_marketdata import (
    IBMarketDataService,
    QuoteSnapshotApp,
    TickTypeEnum,
    _normalize_symbol,
)


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


def test_apply_snapshot_rejects_negative_prices():
    service = IBMarketDataService()
    leg: dict[str, float] = {}

    service._apply_snapshot(leg, {"bid": -1.0, "ask": 0.6})

    assert "mid" not in leg
    assert math.isclose(leg.get("ask"), 0.6)
    assert "bid" not in leg
    assert leg.get("missing_edge") is True


def test_apply_snapshot_uses_last_when_bid_missing():
    service = IBMarketDataService()
    leg: dict[str, float] = {}

    service._apply_snapshot(leg, {"bid": -1.0, "ask": -1.0, "last": 0.4})

    assert math.isclose(leg["mid"], 0.4)
    assert leg.get("missing_edge") is None


def test_tick_price_ignores_negative_sentinel():
    app = QuoteSnapshotApp()
    req_id = 42
    app.register_request(req_id, snapshot=True)

    app.tickPrice(req_id, TickTypeEnum.BID, -1.0, None)

    assert "bid" not in app._responses[req_id]
    assert not app._event(req_id).is_set()

    app.tickPrice(req_id, TickTypeEnum.ASK, 1.25, None)

    assert math.isclose(app._responses[req_id]["ask"], 1.25)
