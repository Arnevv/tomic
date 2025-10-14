from __future__ import annotations

import json
import types

from tomic.services import order_submission
from tomic.services.order_submission import (
    OrderSubmissionService,
    prepare_order_instructions,
)
from tomic.services.strategy_pipeline import StrategyProposal


def test_prepare_order_instructions(monkeypatch):
    monkeypatch.setattr(order_submission, "Order", lambda: types.SimpleNamespace())
    proposal = StrategyProposal(
        strategy="short_put_spread",
        legs=[
            {"symbol": "AAA", "expiry": "20240119", "strike": 100.0, "type": "put", "position": -1},
            {"symbol": "AAA", "expiry": "20240119", "strike": 95.0, "type": "put", "position": 1},
        ],
    )
    instructions = prepare_order_instructions(
        proposal,
        symbol="AAA",
        account="DU123",
        order_type="LMT",
        tif="DAY",
    )
    assert len(instructions) == 2
    first, second = instructions
    assert first.order.action == "SELL"
    assert second.order.action == "BUY"
    assert first.order.totalQuantity == 1
    assert first.order.transmit is False
    assert getattr(first.contract, "lastTradeDateOrContractMonth", None) == "20240119"


def test_dump_order_log(tmp_path, monkeypatch):
    monkeypatch.setattr(order_submission, "Order", lambda: types.SimpleNamespace())
    proposal = StrategyProposal(
        strategy="short_call",
        legs=[
            {"symbol": "AAA", "expiry": "20240119", "strike": 100.0, "type": "call", "position": -1},
        ],
    )
    instructions = prepare_order_instructions(proposal, symbol="AAA")
    path = OrderSubmissionService.dump_order_log(instructions, directory=tmp_path)
    payload = json.loads(path.read_text())
    assert payload[0]["order"]["orderType"] == "LMT"
    assert payload[0]["contract"]["expiry"] == "20240119"


def test_place_orders_uses_parent_child(monkeypatch):
    monkeypatch.setattr(order_submission, "Order", lambda: types.SimpleNamespace())
    proposal = StrategyProposal(
        strategy="short_put_spread",
        legs=[
            {"symbol": "AAA", "expiry": "20240119", "strike": 100.0, "type": "put", "position": -1},
            {"symbol": "AAA", "expiry": "20240119", "strike": 95.0, "type": "put", "position": 1},
        ],
    )
    instructions = prepare_order_instructions(proposal, symbol="AAA")

    class DummyApp(order_submission.OrderPlacementApp):
        def __init__(self):
            super().__init__()
            self.next_valid_id = 50
            self.next_order_id_ready = True
            self.placed: list[tuple[int, str, int | None]] = []

        def placeOrder(self, orderId, contract, order):  # type: ignore[override]
            self.placed.append((orderId, order.action, getattr(order, "parentId", None)))

        def disconnect(self):  # type: ignore[override]
            pass

    dummy = DummyApp()
    monkeypatch.setattr(order_submission, "connect_ib", lambda **kwargs: kwargs.get("app"))
    service = OrderSubmissionService(app_factory=lambda: dummy)
    app, order_ids = service.place_orders(
        instructions,
        host="127.0.0.1",
        port=7497,
        client_id=123,
        timeout=1,
    )
    assert order_ids == [50, 51]
    assert dummy.placed[0] == (50, "SELL", None)
    assert dummy.placed[1] == (51, "BUY", 50)
    assert app is dummy
