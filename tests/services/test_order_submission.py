from __future__ import annotations

import json
import math
import types
from typing import Any

import pytest

from tomic.core.pricing import SpreadPolicy
from tomic.services import order_submission
from tomic.services.order_submission import (
    OrderSubmissionService,
    prepare_order_instructions,
)
from tests.pricing.test_spread_policy import (
    SHARED_POLICY_CONFIG,
    SHARED_SPREAD_SCENARIOS,
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
                "bid": 1.5,
                "ask": 1.6,
                "quote_age_sec": 1.0,
                "mid_source": "true",
            },
            {
                "symbol": "AAA",
                "expiry": "20240119",
                "strike": 95.0,
                "type": "put",
                "position": 1,
                "conId": 102,
                "bid": 0.7,
                "ask": 0.8,
                "quote_age_sec": 1.0,
                "mid_source": "true",
            },
        ],
    )
    proposal.credit = 80.0
    instructions = prepare_order_instructions(
        proposal,
        symbol="AAA",
        account="DU123",
        order_type="LMT",
        tif="DAY",
    )
    assert len(instructions) == 1
    instr = instructions[0]
    assert getattr(instr.order, "action", None) == "BUY"
    assert getattr(instr.order, "totalQuantity", None) == 1
    assert getattr(instr.order, "transmit", None) is True
    assert getattr(instr.contract, "secType", None) == "BAG"
    combo_legs = getattr(instr.contract, "comboLegs", [])
    assert combo_legs and len(combo_legs) == 2
    assert getattr(combo_legs[0], "ratio", None) == 1
    assert getattr(instr.contract, "symbol", None) == "AAA"


def test_prepare_order_blocks_preview_mid(monkeypatch):
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
                "conId": 301,
                "bid": 1.5,
                "ask": 1.6,
                "quote_age_sec": 1.0,
                "mid_source": "model",
            },
            {
                "symbol": "AAA",
                "expiry": "20240119",
                "strike": 95.0,
                "type": "put",
                "position": 1,
                "conId": 302,
                "bid": 0.7,
                "ask": 0.8,
                "quote_age_sec": 1.0,
                "mid_source": "model",
            },
        ],
    )
    proposal.credit = 80.0

    with pytest.raises(ValueError):
        prepare_order_instructions(proposal, symbol="AAA")


def test_validate_instructions_credit_direction_ok():
    contract = types.SimpleNamespace(secType="BAG", comboLegs=[], exchange="SMART")
    order = types.SimpleNamespace(action="BUY", totalQuantity=1, orderType="LMT")
    instr = order_submission.OrderInstruction(
        contract=contract,
        order=order,
        legs=[],
        credit_per_combo=250.0,
    )
    order_submission._validate_instructions([instr])


def test_validate_instructions_credit_direction_error():
    contract = types.SimpleNamespace(secType="BAG", comboLegs=[], exchange="SMART")
    order = types.SimpleNamespace(action="SELL", totalQuantity=1, orderType="LMT")
    instr = order_submission.OrderInstruction(
        contract=contract,
        order=order,
        legs=[],
        credit_per_combo=250.0,
    )
    with pytest.raises(ValueError, match="Inconsistent combo direction vs credit/debit"):
        order_submission._validate_instructions([instr])


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
                "bid": 2.0,
                "ask": 2.1,
                "quote_age_sec": 1.0,
                "mid_source": "true",
            },
            {
                "symbol": "HD",
                "expiry": "20240119",
                "strike": 315.0,
                "type": "call",
                "position": 1,
                "conId": 202,
                "bid": 1.1,
                "ask": 1.2,
                "quote_age_sec": 1.0,
                "mid_source": "true",
            },
        ],
    )
    proposal.credit = 90.0
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


@pytest.mark.parametrize("case", SHARED_SPREAD_SCENARIOS, ids=lambda case: case["description"])
def test_tradeability_aligns_with_shared_policy(case):
    policy = SpreadPolicy(SHARED_POLICY_CONFIG)
    width = float(case["spread"])
    mid = float(case["mid"])
    bid = max(mid - width / 2, 0.01)
    ask = mid + width / 2
    underlying = case.get("underlying")
    legs = [
        order_submission._LegSummary(
            strike=100.0,
            expiry="20240119",
            right="call",
            position=-1.0,
            qty=1,
            bid=1.5,
            ask=1.6,
            min_tick=0.01,
            quote_age_sec=1.0,
            mid_source="true",
            one_sided=False,
            underlying_price=underlying,
        ),
        order_submission._LegSummary(
            strike=95.0,
            expiry="20240119",
            right="call",
            position=1.0,
            qty=1,
            bid=0.9,
            ask=1.0,
            min_tick=0.01,
            quote_age_sec=1.0,
            mid_source="true",
            one_sided=False,
            underlying_price=underlying,
        ),
    ]
    combo_quote = order_submission.ComboQuote(bid=bid, ask=ask, mid=mid, width=width)
    context = dict(case.get("context", {}) or {})
    context.setdefault("symbol", "TST")
    gate_ok, _ = order_submission._evaluate_tradeability(
        legs,
        combo_quote,
        spread_policy=policy,
        policy_context=context,
        underlying_price=underlying,
    )
    assert gate_ok is case["expected"]


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
                "bid": 1.6,
                "ask": 1.7,
                "quote_age_sec": 1.0,
                "mid_source": "true",
            },
            {
                "symbol": "AAA",
                "expiry": "20240119",
                "strike": 95.0,
                "type": "put",
                "position": 1,
                "conId": 402,
                "bid": 0.8,
                "ask": 0.9,
                "quote_age_sec": 1.0,
                "mid_source": "true",
            },
        ],
    )
    proposal.credit = 80.0
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
                self._order_events[order_id] = {
                    "status": "Filled",
                    "filled": 1.0,
                    "remaining": 0.0,
                }

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
    assert dummy.placed == [(50, "BUY", None)]
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
                "bid": 1.6,
                "ask": 1.7,
                "quote_age_sec": 1.0,
                "mid_source": "true",
            },
            {
                "symbol": "AAA",
                "expiry": "20240119",
                "strike": 95.0,
                "type": "put",
                "position": 2,
                "conId": 502,
                "bid": 0.8,
                "ask": 0.9,
                "quote_age_sec": 1.0,
                "mid_source": "true",
            },
        ],
    )
    proposal.credit = 160.0
    instructions = prepare_order_instructions(proposal, symbol="AAA", order_type="LMT")
    assert len(instructions) == 1
    instr = instructions[0]
    assert getattr(instr.order, "totalQuantity", None) == 2
    assert getattr(instr.order, "orderType", None) == "LMT"
    assert getattr(instr.order, "lmtPrice", None) == 0.8


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
                "mid": 7.35,
                "bid": 7.3,
                "ask": 7.4,
                "quote_age_sec": 1.0,
                "mid_source": "true",
            },
            {
                "symbol": "GLD",
                "expiry": "20240216",
                "strike": 180.0,
                "type": "put",
                "position": -1,
                "conId": 1102,
                "mid": 7.35,
                "bid": 7.3,
                "ask": 7.4,
                "quote_age_sec": 1.0,
                "mid_source": "true",
            },
            {
                "symbol": "GLD",
                "expiry": "20240216",
                "strike": 190.0,
                "type": "call",
                "position": 1,
                "conId": 1103,
                "mid": 2.6,
                "bid": 2.59,
                "ask": 2.61,
                "quote_age_sec": 1.0,
                "mid_source": "true",
            },
            {
                "symbol": "GLD",
                "expiry": "20240216",
                "strike": 170.0,
                "type": "put",
                "position": 1,
                "conId": 1104,
                "mid": 2.6,
                "bid": 2.59,
                "ask": 2.61,
                "quote_age_sec": 1.0,
                "mid_source": "true",
            },
        ],
    )
    proposal.credit = 950.0

    instructions = prepare_order_instructions(proposal, symbol="GLD")
    assert len(instructions) == 1
    order = instructions[0].order
    assert math.isclose(getattr(order, "lmtPrice", None) or 0.0, 9.5, rel_tol=1e-4)


def test_combo_credit_width_guard(monkeypatch):
    class DummyOrder(types.SimpleNamespace):
        def __init__(self):
            super().__init__()
            self.lmtPrice = None
            self.smartComboRoutingParams = []

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
                "conId": 1111,
                "mid": 8.0,
                "bid": 7.9,
                "ask": 8.1,
                "quote_age_sec": 1.0,
                "mid_source": "true",
            },
            {
                "symbol": "GLD",
                "expiry": "20240216",
                "strike": 180.0,
                "type": "put",
                "position": -1,
                "conId": 1112,
                "mid": 8.0,
                "bid": 7.9,
                "ask": 8.1,
                "quote_age_sec": 1.0,
                "mid_source": "true",
            },
            {
                "symbol": "GLD",
                "expiry": "20240216",
                "strike": 190.0,
                "type": "call",
                "position": 1,
                "conId": 1113,
                "mid": 2.75,
                "bid": 2.7,
                "ask": 2.8,
                "quote_age_sec": 1.0,
                "mid_source": "true",
            },
            {
                "symbol": "GLD",
                "expiry": "20240216",
                "strike": 170.0,
                "type": "put",
                "position": 1,
                "conId": 1114,
                "mid": 2.75,
                "bid": 2.7,
                "ask": 2.8,
                "quote_age_sec": 1.0,
                "mid_source": "true",
            },
        ],
    )
    proposal.credit = 1500.0

    with pytest.raises(ValueError, match="spread breedte minus marge"):
        prepare_order_instructions(proposal, symbol="GLD")


def _iron_fly_legs(min_tick: float = 0.05) -> list[dict[str, Any]]:
    return [
        {
            "symbol": "AAA",
            "expiry": "20240119",
            "strike": 95.0,
            "type": "put",
            "position": 1,
            "conId": 9101,
            "bid": 1.0,
            "ask": 1.05,
            "minTick": min_tick,
            "quote_age_sec": 1.0,
            "mid_source": "true",
        },
        {
            "symbol": "AAA",
            "expiry": "20240119",
            "strike": 100.0,
            "type": "put",
            "position": -1,
            "conId": 9102,
            "bid": 2.6,
            "ask": 2.65,
            "minTick": min_tick,
            "quote_age_sec": 1.0,
            "mid_source": "true",
        },
        {
            "symbol": "AAA",
            "expiry": "20240119",
            "strike": 100.0,
            "type": "call",
            "position": -1,
            "conId": 9103,
            "bid": 2.6,
            "ask": 2.65,
            "minTick": min_tick,
            "quote_age_sec": 1.0,
            "mid_source": "true",
        },
        {
            "symbol": "AAA",
            "expiry": "20240119",
            "strike": 105.0,
            "type": "call",
            "position": 1,
            "conId": 9104,
            "bid": 1.0,
            "ask": 1.05,
            "minTick": min_tick,
            "quote_age_sec": 1.0,
            "mid_source": "true",
        },
    ]


def _wide_call_vertical(min_tick: float = 0.01) -> list[dict[str, Any]]:
    return [
        {
            "symbol": "AAA",
            "expiry": "20240119",
            "strike": 100.0,
            "type": "call",
            "position": -1,
            "conId": 9201,
            "minTick": min_tick,
            "bid": 4.8,
            "ask": 4.9,
            "quote_age_sec": 1.0,
            "mid_source": "true",
        },
        {
            "symbol": "AAA",
            "expiry": "20240119",
            "strike": 115.0,
            "type": "call",
            "position": 1,
            "conId": 9202,
            "minTick": min_tick,
            "bid": 0.3,
            "ask": 0.35,
            "quote_age_sec": 1.0,
            "mid_source": "true",
        },
    ]


def test_credit_above_width_cap_blocks(monkeypatch):
    class DummyOrder(types.SimpleNamespace):
        def __init__(self):
            super().__init__()
            self.smartComboRoutingParams = []
            self.lmtPrice = None

    monkeypatch.setattr(order_submission, "Order", DummyOrder)
    proposal = StrategyProposal(strategy="iron_fly", legs=_iron_fly_legs())
    proposal.credit = 500.0
    with pytest.raises(ValueError, match="spread breedte minus marge"):
        prepare_order_instructions(proposal, symbol="AAA")


def test_credit_on_width_cap_succeeds(monkeypatch):
    class DummyOrder(types.SimpleNamespace):
        def __init__(self):
            super().__init__()
            self.smartComboRoutingParams = []
            self.lmtPrice = None

    monkeypatch.setattr(order_submission, "Order", DummyOrder)
    proposal = StrategyProposal(strategy="iron_fly", legs=_iron_fly_legs())
    proposal.credit = 320.0
    instructions = prepare_order_instructions(proposal, symbol="AAA")
    assert len(instructions) == 1
    order = instructions[0].order
    assert math.isclose(getattr(order, "lmtPrice", None) or 0.0, 3.2, rel_tol=1e-4)


def test_credit_below_width_cap_succeeds(monkeypatch):
    class DummyOrder(types.SimpleNamespace):
        def __init__(self):
            super().__init__()
            self.smartComboRoutingParams = []
            self.lmtPrice = None

    monkeypatch.setattr(order_submission, "Order", DummyOrder)
    proposal = StrategyProposal(strategy="iron_fly", legs=_iron_fly_legs())
    proposal.credit = 320.0
    instructions = prepare_order_instructions(proposal, symbol="AAA")
    assert len(instructions) == 1
    order = instructions[0].order
    assert math.isclose(getattr(order, "lmtPrice", None) or 0.0, 3.2, rel_tol=1e-4)


def test_iron_structure_rejects_reversed_wings(monkeypatch):
    class DummyOrder(types.SimpleNamespace):
        def __init__(self):
            super().__init__()
            self.smartComboRoutingParams = []
            self.lmtPrice = None

    monkeypatch.setattr(order_submission, "Order", DummyOrder)
    legs = _iron_fly_legs()
    for leg in legs:
        if leg["strike"] in {95.0, 105.0}:
            leg["position"] = -abs(leg["position"])
    proposal = StrategyProposal(strategy="iron_fly", legs=legs)
    proposal.credit = 450.0
    with pytest.raises(ValueError, match="longs horen op de wings"):
        prepare_order_instructions(proposal, symbol="AAA")


def test_contract_credit_converts_to_limit_price(monkeypatch):
    class DummyOrder(types.SimpleNamespace):
        def __init__(self):
            super().__init__()
            self.smartComboRoutingParams = []
            self.lmtPrice = None

    monkeypatch.setattr(order_submission, "Order", DummyOrder)
    legs = _wide_call_vertical()
    proposal = StrategyProposal(strategy="call_credit_spread", legs=legs)
    proposal.credit = 453.0
    instructions = prepare_order_instructions(proposal, symbol="AAA")
    order = instructions[0].order
    assert math.isclose(getattr(order, "lmtPrice", None) or 0.0, 4.53, rel_tol=1e-4)


def test_scale_guard_detects_bad_conversion():
    order = types.SimpleNamespace(lmtPrice=0.10)
    with pytest.raises(ValueError, match="verkeerde schaal"):
        order_submission._guard_limit_price_scale(order, credit_for_scale=1050.0)


def test_combo_scale_guard_detects_mismatch(monkeypatch):
    class DummyOrder(types.SimpleNamespace):
        def __init__(self):
            super().__init__()
            self.smartComboRoutingParams = []
            self.lmtPrice = None

    monkeypatch.setattr(order_submission, "Order", DummyOrder)
    monkeypatch.setattr(order_submission, "_round_to_tick", lambda price, min_tick=None: 0.10)

    proposal = StrategyProposal(strategy="call_credit_spread", legs=_wide_call_vertical())
    proposal.credit = 1050.0

    with pytest.raises(ValueError, match="wijkt teveel af"):
        prepare_order_instructions(proposal, symbol="AAA")


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
                "bid": 2.0,
                "ask": 2.05,
                "quote_age_sec": 1.0,
                "mid_source": "true",
            },
            {
                "symbol": "AAA",
                "expiry": "20240119",
                "strike": 105.0,
                "type": "call",
                "position": 1,
                "conId": 602,
                "bid": 1.0,
                "ask": 1.05,
                "quote_age_sec": 1.0,
                "mid_source": "true",
            },
            {
                "symbol": "AAA",
                "expiry": "20240119",
                "strike": 90.0,
                "type": "put",
                "position": -1,
                "conId": 603,
                "bid": 2.2,
                "ask": 2.25,
                "quote_age_sec": 1.0,
                "mid_source": "true",
            },
            {
                "symbol": "AAA",
                "expiry": "20240119",
                "strike": 85.0,
                "type": "put",
                "position": 1,
                "conId": 604,
                "bid": 0.8,
                "ask": 0.85,
                "quote_age_sec": 1.0,
                "mid_source": "true",
            },
        ],
    )
    proposal.credit = 240.0
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
                    entry.update({"status": "Filled", "filled": 1.0, "remaining": 0.0})

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


# ============================================================================
# ROBUUSTE ORDER SUBMISSION TESTS
# ============================================================================


def test_quote_age_missing_blocks_order(monkeypatch):
    """Quote-age moet altijd aanwezig zijn."""
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
                "conId": 5001,
                "bid": 1.5,
                "ask": 1.6,
                "quote_age_sec": None,  # Missing!
                "mid_source": "true",
            },
            {
                "symbol": "AAA",
                "expiry": "20240119",
                "strike": 95.0,
                "type": "put",
                "position": 1,
                "conId": 5002,
                "bid": 0.7,
                "ask": 0.8,
                "quote_age_sec": 1.0,
                "mid_source": "true",
            },
        ],
    )
    proposal.credit = 80.0

    with pytest.raises(ValueError, match="quote age is verplicht"):
        prepare_order_instructions(proposal, symbol="AAA")


def test_quote_age_stale_blocks_order(monkeypatch):
    """Stale quotes moeten worden geblokkeerd."""
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
                "conId": 5101,
                "bid": 1.5,
                "ask": 1.6,
                "quote_age_sec": 10.0,  # Stale!
                "mid_source": "true",
            },
            {
                "symbol": "AAA",
                "expiry": "20240119",
                "strike": 95.0,
                "type": "put",
                "position": 1,
                "conId": 5102,
                "bid": 0.7,
                "ask": 0.8,
                "quote_age_sec": 1.0,
                "mid_source": "true",
            },
        ],
    )
    proposal.credit = 80.0

    with pytest.raises(ValueError, match="stale_quote"):
        prepare_order_instructions(proposal, symbol="AAA")


def test_credit_strategy_with_zero_credit_blocks(monkeypatch):
    """Credit-strategieën met credit <= 0 moeten worden geblokkeerd."""
    monkeypatch.setattr(order_submission, "Order", lambda: types.SimpleNamespace())
    proposal = StrategyProposal(
        strategy="iron_condor",  # Credit strategy!
        legs=[
            {
                "symbol": "AAA",
                "expiry": "20240119",
                "strike": 100.0,
                "type": "call",
                "position": -1,
                "conId": 5201,
                "bid": 2.0,
                "ask": 2.05,
                "quote_age_sec": 1.0,
                "mid_source": "true",
            },
            {
                "symbol": "AAA",
                "expiry": "20240119",
                "strike": 105.0,
                "type": "call",
                "position": 1,
                "conId": 5202,
                "bid": 1.0,
                "ask": 1.05,
                "quote_age_sec": 1.0,
                "mid_source": "true",
            },
            {
                "symbol": "AAA",
                "expiry": "20240119",
                "strike": 90.0,
                "type": "put",
                "position": -1,
                "conId": 5203,
                "bid": 2.2,
                "ask": 2.25,
                "quote_age_sec": 1.0,
                "mid_source": "true",
            },
            {
                "symbol": "AAA",
                "expiry": "20240119",
                "strike": 85.0,
                "type": "put",
                "position": 1,
                "conId": 5204,
                "bid": 0.8,
                "ask": 0.85,
                "quote_age_sec": 1.0,
                "mid_source": "true",
            },
        ],
    )
    proposal.credit = 0.0  # Zero credit!

    with pytest.raises(ValueError, match="credit_strategy_non_positive"):
        prepare_order_instructions(proposal, symbol="AAA")


def test_credit_strategy_with_negative_credit_blocks(monkeypatch):
    """Credit-strategieën met negatieve credit moeten worden geblokkeerd."""
    monkeypatch.setattr(order_submission, "Order", lambda: types.SimpleNamespace())
    proposal = StrategyProposal(
        strategy="short_call_credit_spread",
        legs=[
            {
                "symbol": "AAA",
                "expiry": "20240119",
                "strike": 100.0,
                "type": "call",
                "position": -1,
                "conId": 5301,
                "bid": 2.0,
                "ask": 2.1,
                "quote_age_sec": 1.0,
                "mid_source": "true",
            },
            {
                "symbol": "AAA",
                "expiry": "20240119",
                "strike": 105.0,
                "type": "call",
                "position": 1,
                "conId": 5302,
                "bid": 1.0,
                "ask": 1.1,
                "quote_age_sec": 1.0,
                "mid_source": "true",
            },
        ],
    )
    proposal.credit = -50.0  # Negative!

    with pytest.raises(ValueError, match="credit_strategy_non_positive"):
        prepare_order_instructions(proposal, symbol="AAA")


def test_mid_source_model_blocked_by_default(monkeypatch):
    """mid_source='model' moet standaard worden geblokkeerd."""
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
                "conId": 5401,
                "bid": 1.5,
                "ask": 1.6,
                "quote_age_sec": 1.0,
                "mid_source": "model",  # Model source!
            },
            {
                "symbol": "AAA",
                "expiry": "20240119",
                "strike": 95.0,
                "type": "put",
                "position": 1,
                "conId": 5402,
                "bid": 0.7,
                "ask": 0.8,
                "quote_age_sec": 1.0,
                "mid_source": "true",
            },
        ],
    )
    proposal.credit = 80.0

    with pytest.raises(ValueError, match="model pricing niet toegestaan"):
        prepare_order_instructions(proposal, symbol="AAA")


def test_mid_source_model_allowed_with_explicit_permission(monkeypatch):
    """mid_source='model' kan worden toegestaan met expliciete toestemming."""
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
                "conId": 5501,
                "bid": 1.5,
                "ask": 1.6,
                "quote_age_sec": 1.0,
                "mid_source": "model",
            },
            {
                "symbol": "AAA",
                "expiry": "20240119",
                "strike": 95.0,
                "type": "put",
                "position": 1,
                "conId": 5502,
                "bid": 0.7,
                "ask": 0.8,
                "quote_age_sec": 1.0,
                "mid_source": "model",
            },
        ],
    )
    proposal.credit = 80.0

    # Should succeed with explicit permission
    service = OrderSubmissionService(
        allow_fallback=True,
        allowed_fallback_sources=["model"],
    )
    instructions = service.build_instructions(
        proposal,
        symbol="AAA",
    )
    assert len(instructions) == 1


def test_validate_credit_for_strategy_detects_iron_condor():
    """Test dat credit validatie iron_condor herkent als credit-strategie."""
    ok, msg = order_submission._validate_credit_for_strategy(
        0.0,
        strategy="iron_condor",
        structure=None,
    )
    assert not ok
    assert "credit_strategy_non_positive" in msg


def test_validate_credit_for_strategy_detects_iron_fly():
    """Test dat credit validatie iron_fly herkent als credit-strategie."""
    ok, msg = order_submission._validate_credit_for_strategy(
        -10.0,
        strategy="iron_fly",
        structure=None,
    )
    assert not ok
    assert "credit_strategy_non_positive" in msg


def test_validate_credit_for_strategy_allows_positive_credit():
    """Test dat credit validatie positieve credit toestaat."""
    ok, msg = order_submission._validate_credit_for_strategy(
        250.0,
        strategy="iron_condor",
        structure=None,
    )
    assert ok
    assert msg == "credit_ok"


def test_validate_credit_for_strategy_allows_debit_strategy_with_negative():
    """Test dat debit-strategieën negatieve credit mogen hebben."""
    ok, msg = order_submission._validate_credit_for_strategy(
        -100.0,
        strategy="short_put_spread",  # Not a credit strategy
        structure="vertical",
    )
    assert ok
    assert msg == "credit_ok"
