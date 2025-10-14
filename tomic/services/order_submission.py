"""Translate TOMIC proposals to IB order structures."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from pprint import pformat
from typing import Any, Sequence

import math

try:  # pragma: no cover - optional during tests
    from ibapi.contract import ComboLeg, Contract
    from ibapi.order import Order
    from ibapi.order_state import OrderState
except Exception:  # pragma: no cover
    class ComboLeg:  # type: ignore[no-redef]
        pass

    class Contract:  # type: ignore[no-redef]
        pass
    Order = object  # type: ignore[assignment]
    OrderState = object  # type: ignore[assignment]

from tomic.api.base_client import BaseIBApp
from tomic.api.ib_connection import connect_ib
from tomic.config import get as cfg_get
from tomic.logutils import logger
from tomic.metrics import calculate_credit
from tomic.models import OptionContract
from tomic.services.strategy_pipeline import StrategyProposal
from tomic.utils import get_leg_qty, get_leg_right, normalize_leg


def _cfg(key: str, default: Any) -> Any:
    value = cfg_get(key, default)
    return default if value in {None, ""} else value


def _expiry(leg: dict) -> str:
    expiry = leg.get("expiry")
    if not expiry:
        raise ValueError("expiry ontbreekt voor leg")
    digits = "".join(ch for ch in str(expiry) if ch.isdigit())
    if len(digits) == 6:
        digits = "20" + digits
    if len(digits) != 8:
        raise ValueError(f"onbekend expiry formaat: {expiry}")
    return digits


def _leg_symbol(leg: dict, *, fallback: str | None = None) -> str:
    symbol = leg.get("symbol") or fallback
    if not symbol:
        raise ValueError("onderliggende ticker ontbreekt")
    return str(symbol).upper()


def _leg_action(position: float) -> str:
    return "BUY" if position > 0 else "SELL"


def _leg_price(leg: dict) -> float | None:
    for key in ("mid", "last", "ask", "bid"):
        value = leg.get(key)
        try:
            if value is not None:
                return round(float(value), 4)
        except Exception:
            continue
    return None


@dataclass
class OrderInstruction:
    """Single IB order structure derived from one or more legs."""

    contract: Contract
    order: Order
    legs: list[dict]


def _serialize_instruction(instr: "OrderInstruction") -> dict[str, Any]:
    contract = instr.contract
    order = instr.order
    combo_legs: list[dict[str, Any]] = []
    for leg in getattr(contract, "comboLegs", []) or []:
        combo_legs.append(
            {
                "conId": getattr(leg, "conId", None),
                "ratio": getattr(leg, "ratio", None),
                "action": getattr(leg, "action", None),
                "exchange": getattr(leg, "exchange", None),
            }
        )
    contract_data = {
        "symbol": getattr(contract, "symbol", None),
        "secType": getattr(contract, "secType", None),
        "expiry": getattr(contract, "lastTradeDateOrContractMonth", None),
        "strike": getattr(contract, "strike", None),
        "right": getattr(contract, "right", None),
        "exchange": getattr(contract, "exchange", None),
        "currency": getattr(contract, "currency", None),
        "multiplier": getattr(contract, "multiplier", None),
        "tradingClass": getattr(contract, "tradingClass", None),
        "primaryExchange": getattr(contract, "primaryExchange", None),
        "conId": getattr(contract, "conId", None),
    }

    sec_type = contract_data.get("secType")
    filtered_contract: dict[str, Any] = {}
    for key, value in contract_data.items():
        if value in (None, ""):
            continue
        if isinstance(value, (int, float)) and not math.isfinite(float(value)):
            continue
        if key == "conId":
            try:
                if int(value) == 0:
                    continue
            except (TypeError, ValueError):
                pass
        if sec_type == "BAG" and key in {
            "expiry",
            "strike",
            "right",
            "multiplier",
            "tradingClass",
            "primaryExchange",
        }:
            continue
        filtered_contract[key] = value

    if combo_legs:
        filtered_contract["comboLegs"] = combo_legs

    return {
        "contract": filtered_contract,
        "order": {
            "action": getattr(order, "action", None),
            "totalQuantity": getattr(order, "totalQuantity", None),
            "orderType": getattr(order, "orderType", None),
            "lmtPrice": getattr(order, "lmtPrice", None),
            "tif": getattr(order, "tif", None),
            "account": getattr(order, "account", None),
            "parentId": getattr(order, "parentId", None),
            "orderRef": getattr(order, "orderRef", None),
            "transmit": getattr(order, "transmit", None),
        },
        "legs": [
            {
                "strike": leg.get("strike"),
                "expiry": leg.get("expiry"),
                "type": get_leg_right(leg),
                "position": leg.get("position"),
                "qty": get_leg_qty(leg),
            }
            for leg in instr.legs
        ],
    }


class OrderPlacementApp(BaseIBApp):
    """Simple IB app that records placed orders."""

    IGNORED_ERROR_CODES: set[int] = BaseIBApp.IGNORED_ERROR_CODES | {2104, 2106, 2158}

    def __init__(self) -> None:
        super().__init__()
        self._order_events: dict[int, dict[str, Any]] = {}
        self._contract_details_events: dict[int, bool] = {}
        self._validated_conids: set[int] = set()
        self._contract_details_end: set[int] = set()
        self._contract_details_req_map: dict[int, int] = {}
        self._next_contract_details_req_id = 10_000
        self._lock = None
        self.next_order_id_ready = False

    # IB callbacks -------------------------------------------------
    def nextValidId(self, orderId: int) -> None:  # noqa: N802 - IB API
        super().nextValidId(orderId)
        self.next_order_id_ready = True

    def openOrder(self, orderId: int, contract: Contract, order: Order, orderState: OrderState) -> None:  # noqa: N802 - IB API
        logger.info(
            "📨 openOrder "
            f"id={orderId} "
            f"type={order.orderType} "
            f"action={order.action} "
            f"qty={order.totalQuantity}"
        )
        self._order_events[orderId] = {
            "order": order,
            "orderState": orderState,
            "status": None,
        }

    def orderStatus(
        self,
        orderId: int,
        status: str,
        filled: float,
        remaining: float,
        avgFillPrice: float,
        permId: int,
        parentId: int,
        lastFillPrice: float,
        clientId: int,
        whyHeld: str,
        mktCapPrice: float,
    ) -> None:  # noqa: N802 - IB API
        logger.info(
            "📈 orderStatus "
            f"id={orderId} "
            f"status={status} "
            f"filled={filled} "
            f"remaining={remaining}"
        )
        entry = self._order_events.setdefault(
            orderId,
            {
                "order": None,
                "orderState": None,
                "status": None,
            },
        )
        entry.update({
            "status": status,
            "filled": filled,
            "remaining": remaining,
            "avgFillPrice": avgFillPrice,
            "lastFillPrice": lastFillPrice,
        })

    def contractDetails(self, reqId: int, details: Any) -> None:  # noqa: N802 - IB API
        contract = getattr(details, "contract", None)
        con_id = getattr(contract, "conId", None)
        if con_id is not None:
            try:
                self._validated_conids.add(int(con_id))
            except (TypeError, ValueError):
                pass
        self._contract_details_events[reqId] = True

    def contractDetailsEnd(self, reqId: int) -> None:  # noqa: N802 - IB API
        self._contract_details_end.add(reqId)

    def validate_contract_conids(self, con_ids: Sequence[int], *, timeout: float = 3.0) -> None:
        pending: list[int] = []
        for con_id in {int(con_id) for con_id in con_ids if con_id not in (None, 0)}:
            if con_id in self._validated_conids:
                continue
            contract = Contract()
            contract.conId = con_id
            contract.exchange = "SMART"
            req_id = self._next_contract_details_req_id
            self._next_contract_details_req_id += 1
            self._contract_details_req_map[req_id] = con_id
            pending.append(req_id)
            self.reqContractDetails(req_id, contract)

        if not pending:
            return

        start = time.time()
        while time.time() - start < timeout:
            if all(req_id in self._contract_details_end for req_id in pending):
                break
            time.sleep(0.1)

        missing = [
            self._contract_details_req_map[req_id]
            for req_id in pending
            if req_id not in self._contract_details_end
            or not self._contract_details_events.get(req_id)
        ]
        if missing:
            raise RuntimeError(
                "❌ Geen contractDetails ontvangen voor conIds: " + ", ".join(map(str, missing))
            )

        for req_id in pending:
            self._contract_details_req_map.pop(req_id, None)
            self._contract_details_events.pop(req_id, None)
            self._contract_details_end.discard(req_id)

    def wait_for_order_handshake(self, order_ids: Sequence[int], *, timeout: float = 3.0) -> None:
        if not order_ids:
            return

        try:
            self.reqOpenOrders()
        except Exception:
            logger.debug("Kon reqOpenOrders niet uitvoeren", exc_info=True)

        start = time.time()
        requested_all = False
        while time.time() - start < timeout:
            all_orders_terminal = True
            for order_id in order_ids:
                event = self._order_events.get(order_id)
                status = event.get("status") if event else None

                # Wacht tot de order een definitieve status heeft bereikt.
                if status is None or status in {"ApiPending", "PendingSubmit"}:
                    all_orders_terminal = False
                    break

            if all_orders_terminal:
                logger.debug("✅ Alle orders hebben een definitieve status bereikt.")
                return
            if not requested_all and time.time() - start > timeout / 2:
                try:
                    self.reqAllOpenOrders()
                except Exception:
                    logger.debug("Kon reqAllOpenOrders niet uitvoeren", exc_info=True)
                requested_all = True
            time.sleep(0.1)
        logger.warning(
            "⏱ Timeout bij wachten op bevestiging van orders: %s",
            ", ".join(map(str, order_ids)),
        )


class OrderSubmissionService:
    """Translate and submit strategy proposals as IB concept orders."""

    def __init__(self, *, app_factory: type[OrderPlacementApp] = OrderPlacementApp) -> None:
        self._app_factory = app_factory

    # ------------------------------------------------------------------
    def build_instructions(
        self,
        proposal: StrategyProposal,
        *,
        symbol: str,
        account: str | None = None,
        order_type: str | None = None,
        tif: str | None = None,
    ) -> list[OrderInstruction]:
        leg_contracts: list[tuple[dict, Contract, int, str, float | None]] = []
        for leg in proposal.legs:
            normalize_leg(leg)
            qty = int(get_leg_qty(leg))
            if qty <= 0:
                raise ValueError("ongeldige hoeveelheid voor leg")
            right = get_leg_right(leg)
            if right not in {"call", "put"}:
                raise ValueError("onbekend optietype")
            position = float(leg.get("position") or leg.get("qty") or 0)
            if position == 0:
                position = -qty
            leg_con_id = leg.get("conId") or leg.get("con_id")
            if not leg_con_id:
                raise ValueError("conId ontbreekt voor leg")
            try:
                leg_con_id_int = int(leg_con_id)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"ongeldige conId voor leg: {leg_con_id}") from exc
            contract = OptionContract(
                symbol=_leg_symbol(leg, fallback=symbol),
                expiry=_expiry(leg),
                strike=float(leg.get("strike")),
                right=right[:1].upper(),
                exchange=str(leg.get("exchange") or _cfg("OPTIONS_EXCHANGE", "SMART")),
                currency=str(leg.get("currency") or "USD"),
                multiplier=str(leg.get("multiplier") or "100"),
                trading_class=leg.get("tradingClass") or leg.get("trading_class"),
                primary_exchange=leg.get("primaryExchange") or leg.get("primary_exchange"),
                con_id=leg_con_id_int,
            ).to_ib()
            contract_con_id = getattr(contract, "conId", None)
            if contract_con_id in (None, 0):
                raise ValueError("ongeldige conId voor leg")
            action = _leg_action(position)
            price = _leg_price(leg)
            leg_contracts.append((leg, contract, qty, action, price))

        if not leg_contracts:
            return []

        if len(leg_contracts) == 1:
            leg, contract, qty, action, price = leg_contracts[0]
            order = Order()
            order.totalQuantity = qty
            order.action = action
            order.orderType = (order_type or _cfg("DEFAULT_ORDER_TYPE", "LMT")).upper()
            order.tif = (tif or _cfg("DEFAULT_TIME_IN_FORCE", "DAY")).upper()
            if price is not None and hasattr(order, "lmtPrice"):
                order.lmtPrice = round(price, 2)
            order.transmit = True
            order.account = account or "DUK809533"
            order.orderRef = f"{proposal.strategy}-{symbol}"
            return [OrderInstruction(contract=contract, order=order, legs=[leg])]

        legs = [item[0] for item in leg_contracts]
        contracts = [item[1] for item in leg_contracts]
        qtys = [item[2] for item in leg_contracts]
        combo_contract = Contract()
        first_contract = contracts[0]
        combo_contract.symbol = getattr(first_contract, "symbol", _leg_symbol(legs[0], fallback=symbol))
        combo_contract.secType = "BAG"
        combo_contract.currency = getattr(first_contract, "currency", "USD")
        combo_contract.exchange = "SMART"
        combo_contract.comboLegs = []  # type: ignore[assignment]
        # Ensure the BAG contract is "clean" and does not inherit default
        # option attributes (e.g. absurd default strikes) that IB will reject.
        combo_contract.lastTradeDateOrContractMonth = ""
        combo_contract.strike = 0.0
        combo_contract.right = ""
        combo_contract.multiplier = ""
        combo_contract.tradingClass = ""
        combo_contract.primaryExchange = ""

        combo_quantity = math.gcd(*qtys)
        if combo_quantity <= 0:
            combo_quantity = 1

        for leg, contract, qty, action, _ in leg_contracts:
            ratio = max(1, qty // combo_quantity)
            combo_leg = ComboLeg()
            con_id = getattr(contract, "conId", None)
            if con_id in (None, 0):
                raise ValueError("combo leg mist conId")
            try:
                combo_leg.conId = int(con_id)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"ongeldige combo leg conId: {con_id}") from exc
            combo_leg.ratio = ratio
            combo_leg.action = action
            combo_leg.exchange = "SMART"
            combo_contract.comboLegs.append(combo_leg)  # type: ignore[attr-defined]

        order = Order()
        order.totalQuantity = combo_quantity
        net_credit = proposal.credit
        if net_credit is None:
            net_credit = calculate_credit(legs)
        per_combo_credit = None
        if net_credit is not None:
            try:
                per_combo_credit = net_credit / max(combo_quantity, 1)
            except Exception:
                per_combo_credit = net_credit
        if per_combo_credit is not None:
            net_price = round(abs(per_combo_credit / 100.0), 2)
        else:
            net_price = None
        order.orderType = "MIDPRICE"
        order.tif = (tif or _cfg("DEFAULT_TIME_IN_FORCE", "DAY")).upper()
        order.action = "SELL" if (net_credit or 0) >= 0 else "BUY"
        order.transmit = True
        order.account = account or "DUK809533"
        order.orderRef = f"{proposal.strategy}-{symbol}"
        return [OrderInstruction(contract=combo_contract, order=order, legs=list(legs))]

    # ------------------------------------------------------------------
    def place_orders(
        self,
        instructions: Sequence[OrderInstruction],
        *,
        host: str,
        port: int,
        client_id: int,
        timeout: int = 5,
    ) -> tuple[OrderPlacementApp, list[int]]:
        if not instructions:
            raise ValueError("geen orders om te plaatsen")
        app = self._app_factory()
        connect_ib(host=host, port=port, client_id=client_id, timeout=timeout, app=app)
        try:
            while not getattr(app, "next_order_id_ready", False):
                time.sleep(0.1)
            order_id = app.next_valid_id or 1
            con_ids_to_validate: set[int] = set()
            for instr in instructions:
                contract_con_id = getattr(instr.contract, "conId", None)
                if contract_con_id not in (None, 0):
                    try:
                        con_ids_to_validate.add(int(contract_con_id))
                    except (TypeError, ValueError) as exc:
                        raise ValueError(
                            f"ongeldige contract conId: {contract_con_id}"
                        ) from exc
                combo_legs = getattr(instr.contract, "comboLegs", None) or []
                for combo_leg in combo_legs:
                    con_id = getattr(combo_leg, "conId", None)
                    if con_id in (None, 0):
                        raise ValueError("combo leg mist conId")
                    try:
                        con_ids_to_validate.add(int(con_id))
                    except (TypeError, ValueError) as exc:
                        raise ValueError(
                            f"ongeldige combo leg conId: {con_id}"
                        ) from exc

            if con_ids_to_validate:
                app.validate_contract_conids(sorted(con_ids_to_validate))
            placed_ids: list[int] = []
            parent_id = order_id
            for idx, instr in enumerate(instructions):
                current_id = order_id + idx
                order = instr.order
                if idx == 0:
                    parent_id = current_id
                else:
                    order.parentId = parent_id
                payload = _serialize_instruction(instr)
                logger.debug(
                    f"IB order payload id={current_id} ->\n{pformat(payload)}"
                )

                contract = instr.contract
                parts: list[str] = [
                    f"id={current_id}",
                    f"action={getattr(order, 'action', '?')}",
                    f"qty={getattr(order, 'totalQuantity', '?')}",
                    f"type={getattr(order, 'orderType', '?')}",
                ]
                price = getattr(order, "lmtPrice", None)
                if price not in (None, "", "-"):
                    parts.append(f"limit={price}")
                contract_bits: list[str] = []
                symbol = getattr(contract, "symbol", None)
                if symbol:
                    contract_bits.append(str(symbol))
                sec_type = getattr(contract, "secType", None)
                if sec_type:
                    contract_bits.append(str(sec_type))
                expiry = getattr(contract, "lastTradeDateOrContractMonth", None)
                if expiry:
                    contract_bits.append(str(expiry))
                strike = getattr(contract, "strike", None)
                if strike not in (None, ""):
                    contract_bits.append(str(strike))
                right = getattr(contract, "right", None)
                if right:
                    contract_bits.append(str(right))
                if contract_bits:
                    parts.append(f"contract={' '.join(contract_bits)}")
                legs_info = [
                    f"{get_leg_right(leg)} {leg.get('strike')} ({leg.get('position')})"
                    for leg in instr.legs
                ]
                if legs_info:
                    parts.append("legs=" + ", ".join(legs_info))
                logger.info(f"🚀 Verstuur order {' | '.join(parts)}")
                app.placeOrder(current_id, instr.contract, order)
                placed_ids.append(current_id)
            app.wait_for_order_handshake(placed_ids)
            return app, placed_ids
        except Exception:
            logger.exception("❌ Fout bij versturen van IB orders")
            raise
    # ------------------------------------------------------------------
    @staticmethod
    def dump_order_log(
        instructions: Sequence[OrderInstruction],
        *,
        directory: Path,
    ) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = directory / f"order_submission_{ts}.json"
        payload = [_serialize_instruction(instr) for instr in instructions]
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path


def prepare_order_instructions(
    proposal: StrategyProposal,
    *,
    symbol: str,
    account: str | None = None,
    order_type: str | None = None,
    tif: str | None = None,
    service: OrderSubmissionService | None = None,
) -> list[OrderInstruction]:
    svc = service or OrderSubmissionService()
    return svc.build_instructions(
        proposal,
        symbol=symbol,
        account=account,
        order_type=order_type,
        tif=tif,
    )


__all__ = [
    "OrderInstruction",
    "OrderPlacementApp",
    "OrderSubmissionService",
    "prepare_order_instructions",
]

