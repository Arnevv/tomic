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
            {
                "symbol": "AAA",
                "expiry": "20240119",
                "strike": 100.0,
                "type": "put",
                "position": -1,
                "conId": 101,
            },
            {
                "symbol": "AAA",
                "expiry": "20240119",
                "strike": 95.0,
                "type": "put",
                "position": 1,
                "conId": 102,
            },
        ],
    )
    instructions = prepare_order_instructions(
        proposal,
        symbol="AAA",
        account="DU123",
        order_type="LMT",
        tif="DAY",
    )
    assert len(instructions) == 1
    instr = instructions[0]
    assert getattr(instr.order, "action", None) == "SELL"
    assert getattr(instr.order, "totalQuantity", None) == 1
    assert getattr(instr.order, "transmit", None) is True
    assert getattr(instr.contract, "secType", None) == "BAG"
    combo_legs = getattr(instr.contract, "comboLegs", [])
    assert combo_legs and len(combo_legs) == 2
    assert getattr(combo_legs[0], "ratio", None) == 1
    assert getattr(instr.contract, "symbol", None) == "AAA"


def test_bag_contract_excludes_disallowed_fields(monkeypatch):
    monkeypatch.setattr(order_submission, "Order", lambda: types.SimpleNamespace())
    proposal = StrategyProposal(
        strategy="short_put_spread",
        legs=[
            {
                "symbol": "HD",
                "expiry": "20240119",
                "strike": 310.0,
                "type": "call",
                "position": -1,
                "conId": 201,
            },
            {
                "symbol": "HD",
                "expiry": "20240119",
                "strike": 305.0,
                "type": "call",
                "position": 1,
                "conId": 202,
            },
        ],
    )
    instructions = prepare_order_instructions(proposal, symbol="HD")
    assert len(instructions) == 1
    payload = order_submission._serialize_instruction(instructions[0])
    contract = payload["contract"]
    assert contract == {
        "symbol": "HD",
        "secType": "BAG",
        "exchange": "SMART",
        "currency": "USD",
        "comboLegs": [
            {"conId": 201, "ratio": 1, "action": "SELL", "exchange": "SMART"},
            {"conId": 202, "ratio": 1, "action": "BUY", "exchange": "SMART"},
        ],
    }


def test_dump_order_log(tmp_path, monkeypatch):
    monkeypatch.setattr(order_submission, "Order", lambda: types.SimpleNamespace())
    proposal = StrategyProposal(
        strategy="short_call",
        legs=[
            {
                "symbol": "AAA",
                "expiry": "20240119",
                "strike": 100.0,
                "type": "call",
                "position": -1,
                "conId": 301,
            },
        ],
    )
    instructions = prepare_order_instructions(proposal, symbol="AAA")
    path = OrderSubmissionService.dump_order_log(instructions, directory=tmp_path)
    payload = json.loads(path.read_text())
    assert payload[0]["order"]["orderType"] == "LMT"
    assert payload[0]["legs"][0]["expiry"] == "20240119"


def test_place_orders_uses_parent_child(monkeypatch):
    monkeypatch.setattr(order_submission, "Order", lambda: types.SimpleNamespace())
    proposal = StrategyProposal(
        strategy="short_put_spread",
        legs=[
            {
                "symbol": "AAA",
                "expiry": "20240119",
                "strike": 100.0,
                "type": "put",
                "position": -1,
                "conId": 401,
            },
            {
                "symbol": "AAA",
                "expiry": "20240119",
                "strike": 95.0,
                "type": "put",
                "position": 1,
                "conId": 402,
            },
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

        def validate_contract_conids(self, con_ids, *, timeout: float = 3.0):  # type: ignore[override]
            self._validated_conids.update(int(con_id) for con_id in con_ids)

        def wait_for_order_handshake(self, order_ids, *, timeout: float = 3.0):  # type: ignore[override]
            for order_id in order_ids:
                self._order_events[order_id] = {"status": "Submitted"}

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
    assert order_ids == [50]
    assert dummy.placed == [(50, "SELL", None)]
    assert app is dummy


def test_combo_limit_price_divides_by_quantity(monkeypatch):
    class DummyOrder(types.SimpleNamespace):
        def __init__(self):
            super().__init__()
            self.lmtPrice = None

    monkeypatch.setattr(order_submission, "Order", DummyOrder)
    proposal = StrategyProposal(
        strategy="short_put_spread",
        legs=[
            {
                "symbol": "AAA",
                "expiry": "20240119",
                "strike": 100.0,
                "type": "put",
                "position": -2,
                "conId": 501,
            },
            {
                "symbol": "AAA",
                "expiry": "20240119",
                "strike": 95.0,
                "type": "put",
                "position": 2,
                "conId": 502,
            },
        ],
    )
    proposal.credit = 200.0
    instructions = prepare_order_instructions(proposal, symbol="AAA", order_type="LMT")
    assert len(instructions) == 1
    instr = instructions[0]
    assert getattr(instr.order, "totalQuantity", None) == 2
    assert getattr(instr.order, "orderType", None) == "MIDPRICE"
    assert getattr(instr.order, "lmtPrice", None) is None
