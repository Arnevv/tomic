from __future__ import annotations

import json
import math
import types

import pytest

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
    assert getattr(instr.order, "orderType", None) == "LMT"
    assert getattr(instr.order, "lmtPrice", None) == 1.0


def test_combo_mid_credit_converts_to_per_share_limit(monkeypatch):
    class DummyOrder(types.SimpleNamespace):
        def __init__(self):
            super().__init__()
            self.smartComboRoutingParams = []
            self.lmtPrice = None

    monkeypatch.setattr(order_submission, "Order", DummyOrder)
    proposal = StrategyProposal(
        strategy="iron_butterfly",
        legs=[
            {
                "symbol": "GLD",
                "expiry": "20240216",
                "strike": 180.0,
                "type": "call",
                "position": -1,
                "conId": 1101,
                "mid": 8.0,
            },
            {
                "symbol": "GLD",
                "expiry": "20240216",
                "strike": 180.0,
                "type": "put",
                "position": -1,
                "conId": 1102,
                "mid": 8.0,
            },
            {
                "symbol": "GLD",
                "expiry": "20240216",
                "strike": 190.0,
                "type": "call",
                "position": 1,
                "conId": 1103,
                "mid": 2.75,
            },
            {
                "symbol": "GLD",
                "expiry": "20240216",
                "strike": 170.0,
                "type": "put",
                "position": 1,
                "conId": 1104,
                "mid": 2.75,
            },
        ],
    )
    proposal.credit = 1050.0

    instructions = prepare_order_instructions(proposal, symbol="GLD")
    assert len(instructions) == 1
    order = instructions[0].order
    assert math.isclose(getattr(order, "lmtPrice", None) or 0.0, 10.49, rel_tol=1e-4)


def test_combo_scale_guard_detects_mismatch(monkeypatch):
    class DummyOrder(types.SimpleNamespace):
        def __init__(self):
            super().__init__()
            self.smartComboRoutingParams = []
            self.lmtPrice = None

    monkeypatch.setattr(order_submission, "Order", DummyOrder)
    monkeypatch.setattr(order_submission, "_combo_mid_credit", lambda legs: 10.5)

    proposal = StrategyProposal(
        strategy="iron_butterfly",
        legs=[
            {
                "symbol": "GLD",
                "expiry": "20240216",
                "strike": 180.0,
                "type": "call",
                "position": -1,
                "conId": 2101,
                "mid": 8.0,
            },
            {
                "symbol": "GLD",
                "expiry": "20240216",
                "strike": 180.0,
                "type": "put",
                "position": -1,
                "conId": 2102,
                "mid": 8.0,
            },
            {
                "symbol": "GLD",
                "expiry": "20240216",
                "strike": 190.0,
                "type": "call",
                "position": 1,
                "conId": 2103,
                "mid": 2.75,
            },
            {
                "symbol": "GLD",
                "expiry": "20240216",
                "strike": 170.0,
                "type": "put",
                "position": 1,
                "conId": 2104,
                "mid": 2.75,
            },
        ],
    )
    proposal.credit = 1050.0

    with pytest.raises(ValueError, match="schaalfout"):
        prepare_order_instructions(proposal, symbol="GLD")


def test_combo_with_more_than_two_legs_omits_non_guaranteed(monkeypatch):
    class DummyOrder(types.SimpleNamespace):
        def __init__(self):
            super().__init__()
            self.smartComboRoutingParams = []
            self.lmtPrice = None

    monkeypatch.setattr(order_submission, "Order", DummyOrder)
    proposal = StrategyProposal(
        strategy="iron_condor",
        legs=[
            {
                "symbol": "AAA",
                "expiry": "20240119",
                "strike": 100.0,
                "type": "call",
                "position": -1,
                "conId": 601,
            },
            {
                "symbol": "AAA",
                "expiry": "20240119",
                "strike": 105.0,
                "type": "call",
                "position": 1,
                "conId": 602,
            },
            {
                "symbol": "AAA",
                "expiry": "20240119",
                "strike": 90.0,
                "type": "put",
                "position": -1,
                "conId": 603,
            },
            {
                "symbol": "AAA",
                "expiry": "20240119",
                "strike": 85.0,
                "type": "put",
                "position": 1,
                "conId": 604,
            },
        ],
    )
    instructions = prepare_order_instructions(proposal, symbol="AAA")
    assert len(instructions) == 1
    order = instructions[0].order
    params = getattr(order, "smartComboRoutingParams", None)
    assert params == []


def test_place_orders_rejects_multi_leg_non_guaranteed(monkeypatch):
    order = types.SimpleNamespace(
        totalQuantity=1,
        action="SELL",
        orderType="LMT",
        smartComboRoutingParams=[order_submission.TagValue("NonGuaranteed", "1")],
    )
    combo_legs = [
        types.SimpleNamespace(conId=701),
        types.SimpleNamespace(conId=702),
        types.SimpleNamespace(conId=703),
    ]
    contract = types.SimpleNamespace(secType="BAG", comboLegs=combo_legs, exchange="SMART")
    instructions = [
        order_submission.OrderInstruction(contract=contract, order=order, legs=[])
    ]
    service = OrderSubmissionService()

    def fail_connect(**kwargs):  # pragma: no cover - should not be called
        raise AssertionError("connect_ib mag niet aangeroepen worden")

    monkeypatch.setattr(order_submission, "connect_ib", fail_connect)

    with pytest.raises(ValueError, match="NonGuaranteed"):
        service.place_orders(
            instructions,
            host="127.0.0.1",
            port=7497,
            client_id=123,
        )


def test_place_orders_retries_after_10043(monkeypatch, caplog):
    caplog.set_level("INFO")
    order = types.SimpleNamespace(
        totalQuantity=1,
        action="SELL",
        orderType="LMT",
        smartComboRoutingParams=[order_submission.TagValue("NonGuaranteed", "1")],
        algoStrategy="",
        algoParams=[],
        tif="DAY",
    )
    combo_legs = [
        types.SimpleNamespace(conId=801, ratio=1, action="SELL", exchange="SMART"),
        types.SimpleNamespace(conId=802, ratio=1, action="BUY", exchange="SMART"),
    ]
    contract = types.SimpleNamespace(
        secType="BAG",
        comboLegs=combo_legs,
        exchange="SMART",
        symbol="AAA",
        currency="USD",
        lastTradeDateOrContractMonth="",
        strike=0.0,
        right="",
    )
    instructions = [
        order_submission.OrderInstruction(contract=contract, order=order, legs=[])
    ]

    attempts: dict[str, int] = {"count": 0}
    created_apps: list[order_submission.OrderPlacementApp] = []

    def app_factory():
        attempt_idx = attempts["count"]
        attempts["count"] += 1

        class DummyApp(order_submission.OrderPlacementApp):
            def __init__(self):
                super().__init__()
                self.next_valid_id = 100 + attempt_idx * 10
                self.next_order_id_ready = True
                self.placed: list[tuple[int, list[str]]] = []
                self._attempt_idx = attempt_idx

            def placeOrder(self, orderId, contract, order):  # type: ignore[override]
                params = [getattr(param, "tag", None) for param in getattr(order, "smartComboRoutingParams", []) or []]
                self.placed.append((orderId, params))
                entry = self._order_events.setdefault(
                    orderId,
                    {"order": order, "orderState": None, "status": None},
                )
                if self._attempt_idx == 0:
                    entry["status"] = "ApiPending"
                    self.error(orderId, 0, 10043, "NonGuaranteed combos not allowed")
                else:
                    entry["status"] = "Submitted"

            def wait_for_order_handshake(self, order_ids, *, timeout: float = 3.0):  # type: ignore[override]
                return super().wait_for_order_handshake(order_ids, timeout=timeout)

            def disconnect(self):  # type: ignore[override]
                pass

            def validate_contract_conids(self, con_ids, *, timeout: float = 3.0):  # type: ignore[override]
                self._validated_conids.update(int(con_id) for con_id in con_ids)

        app = DummyApp()
        created_apps.append(app)
        return app

    monkeypatch.setattr(order_submission, "connect_ib", lambda **kwargs: kwargs.get("app"))
    logged_infos: list[str] = []

    def capture_info(message, *args, **kwargs):
        try:
            formatted = message % args if args else message
        except Exception:  # pragma: no cover - defensive
            formatted = str(message)
        logged_infos.append(formatted)

    monkeypatch.setattr(order_submission.logger, "info", capture_info)
    service = OrderSubmissionService(app_factory=app_factory)

    app, order_ids = service.place_orders(
        instructions,
        host="127.0.0.1",
        port=7497,
        client_id=123,
    )

    assert attempts["count"] == 2
    assert app is created_apps[-1]
    assert order_ids == [110]
    first_attempt_params = created_apps[0].placed[0][1]
    second_attempt_params = created_apps[1].placed[0][1]
    assert "NonGuaranteed" in first_attempt_params
    assert second_attempt_params == []
    assert getattr(order, "smartComboRoutingParams", None) == []
    assert any(
        "retry_reason=remove_non_guaranteed_for_multi_leg_combo" in msg
        for msg in logged_infos
    )
