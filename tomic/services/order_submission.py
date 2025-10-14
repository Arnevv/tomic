"""Translate TOMIC proposals to IB order structures."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
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


class OrderPlacementApp(BaseIBApp):
    """Simple IB app that records placed orders."""

    IGNORED_ERROR_CODES: set[int] = BaseIBApp.IGNORED_ERROR_CODES | {2104, 2106, 2158}

    def __init__(self) -> None:
        super().__init__()
        self._order_events: dict[int, tuple[Order, OrderState | None]] = {}
        self._lock = None
        self.next_order_id_ready = False

    # IB callbacks -------------------------------------------------
    def nextValidId(self, orderId: int) -> None:  # noqa: N802 - IB API
        super().nextValidId(orderId)
        self.next_order_id_ready = True

    def openOrder(self, orderId: int, contract: Contract, order: Order, orderState: OrderState) -> None:  # noqa: N802 - IB API
        logger.info(
            "📨 openOrder id=%s type=%s action=%s qty=%s", orderId, order.orderType, order.action, order.totalQuantity
        )
        self._order_events[orderId] = (order, orderState)

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
            "📈 orderStatus id=%s status=%s filled=%s remaining=%s", orderId, status, filled, remaining
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
                con_id=leg.get("conId") or leg.get("con_id"),
            ).to_ib()
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
            order.transmit = False
            if account:
                order.account = account
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
        first_exchange = getattr(first_contract, "exchange", None)
        combo_contract.exchange = str(first_exchange or _cfg("OPTIONS_EXCHANGE", "SMART"))
        combo_contract.comboLegs = []  # type: ignore[assignment]

        combo_quantity = math.gcd(*qtys)
        if combo_quantity <= 0:
            combo_quantity = 1

        for leg, contract, qty, action, _ in leg_contracts:
            ratio = max(1, qty // combo_quantity)
            combo_leg = ComboLeg()
            con_id = getattr(contract, "conId", None)
            if con_id not in (None, 0):
                combo_leg.conId = con_id
            combo_leg.ratio = ratio
            combo_leg.action = action
            combo_leg.exchange = getattr(contract, "exchange", combo_contract.exchange)
            combo_contract.comboLegs.append(combo_leg)  # type: ignore[attr-defined]

        order = Order()
        order.totalQuantity = combo_quantity
        net_credit = proposal.credit
        if net_credit is None:
            net_credit = calculate_credit(legs)
        if net_credit is not None:
            net_price = round(abs(net_credit / 100.0), 2)
        else:
            net_price = None
        order.orderType = (order_type or _cfg("DEFAULT_ORDER_TYPE", "LMT")).upper()
        order.tif = (tif or _cfg("DEFAULT_TIME_IN_FORCE", "DAY")).upper()
        if order.orderType == "LMT" and net_price is not None and hasattr(order, "lmtPrice"):
            order.lmtPrice = net_price
        order.action = "SELL" if (net_credit or 0) >= 0 else "BUY"
        order.transmit = False
        if account:
            order.account = account
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
            placed_ids: list[int] = []
            parent_id = order_id
            for idx, instr in enumerate(instructions):
                current_id = order_id + idx
                order = instr.order
                if idx == 0:
                    parent_id = current_id
                else:
                    order.parentId = parent_id
                logger.info(
                    "🚀 Verstuur order id=%s %s %sx%s @%s", current_id, order.action, order.totalQuantity, getattr(instr.contract, "strike", "-"), getattr(order, "lmtPrice", "-")
                )
                app.placeOrder(current_id, instr.contract, order)
                placed_ids.append(current_id)
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
        payload: list[dict[str, Any]] = []
        for instr in instructions:
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
            payload.append(
                {
                    "contract": {
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
                        "comboLegs": combo_legs or None,
                    },
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
            )
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

