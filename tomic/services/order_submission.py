"""Translate TOMIC proposals to IB order structures."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from pprint import pformat
from typing import Any, Sequence

import math

try:  # pragma: no cover - optional during tests
    from ibapi.contract import ComboLeg, Contract
    from ibapi.order import Order
    from ibapi.order_state import OrderState
    from ibapi.tag_value import TagValue
except Exception:  # pragma: no cover
    class ComboLeg:  # type: ignore[no-redef]
        pass

    class Contract:  # type: ignore[no-redef]
        pass
    Order = object  # type: ignore[assignment]
    OrderState = object  # type: ignore[assignment]
    class TagValue:  # type: ignore[no-redef]
        def __init__(self, tag: str, value: str) -> None:
            self.tag = tag
            self.value = value

from tomic.api.base_client import BaseIBApp
from tomic.api.ib_connection import connect_ib
from tomic.helpers.dateutils import normalize_expiry_code
from tomic.helpers.numeric import safe_float
from tomic.logutils import logger
from tomic.metrics import MidPriceResolver, calculate_credit, get_signed_position, iter_leg_views
from tomic.models import OptionContract
from tomic.services._config import cfg_value
from tomic.services.strategy_pipeline import StrategyProposal
from tomic.strategy.reasons import reason_from_mid_source
from tomic.utils import get_leg_qty, get_leg_right, get_option_mid_price, normalize_leg


log = logger
_COMBO_SPREAD_ABS_THRESHOLD = 0.30
_COMBO_SPREAD_REL_THRESHOLD = 0.08
_COMBO_MAX_QUOTE_AGE_SEC = 5.0
_REPRICER_WAIT_SECONDS = 10.0
def _expiry(leg: dict) -> str:
    return normalize_expiry_code(leg.get("expiry"))


def _leg_symbol(leg: dict, *, fallback: str | None = None) -> str:
    symbol = leg.get("symbol") or fallback
    if not symbol:
        raise ValueError("onderliggende ticker ontbreekt")
    return str(symbol).upper()


def _leg_action(position: float) -> str:
    return "BUY" if position > 0 else "SELL"


def _leg_price(leg: dict) -> float | None:
    price, _ = get_option_mid_price(leg)
    if price is not None:
        return round(price, 4)
    return None


def _leg_mid_price(leg: dict) -> float | None:
    """Return best available mid price for ``leg``."""

    price, _used_close = get_option_mid_price(leg)
    return price


def _combo_mid_credit(legs: Sequence[dict]) -> float | None:
    """Return combo mid credit per contract in dollars if prices are available."""

    leg_views = list(iter_leg_views(legs, price_resolver=MidPriceResolver))
    if not leg_views:
        return None
    if any(view.mid is None for view in leg_views):
        return None
    return calculate_credit(leg_views, price_resolver=None)


def _block_order(reason: str, advice: str) -> None:
    """Log a blocking reason and raise an exception."""

    message = f"[order-block] reason={reason} advice={advice}"
    log.error(message)
    raise ValueError(advice)


@dataclass
class ComboQuote:
    bid: float
    ask: float
    mid: float
    width: float


@dataclass
class _LegSummary:
    strike: float
    expiry: str
    right: str
    position: float
    qty: int
    bid: float | None
    ask: float | None
    min_tick: float | None
    quote_age_sec: float | None
    mid_source: str | None
    one_sided: bool = False

    @property
    def is_long(self) -> bool:
        return self.position > 0

    @property
    def is_short(self) -> bool:
        return self.position < 0


def _normalize_leg_summary(leg: dict) -> _LegSummary:
    strike_raw = leg.get("strike")
    if strike_raw in (None, ""):
        _block_order("missing_strike", "leg mist strike")
    try:
        strike = float(strike_raw)
    except Exception as exc:  # pragma: no cover - defensive
        raise ValueError(f"ongeldige strike waarde: {strike_raw}") from exc
    expiry = _expiry(leg)
    right = get_leg_right(leg)
    signed_position = get_signed_position(leg)
    if signed_position == 0:
        signed_position = -float(get_leg_qty(leg))
    qty = int(get_leg_qty(leg))
    bid = safe_float(leg.get("bid"))
    ask = safe_float(leg.get("ask"))
    min_tick = leg.get("minTick")
    if min_tick in (None, ""):
        min_tick = leg.get("min_tick")
    min_tick_value = safe_float(min_tick)
    leg_view = next(iter_leg_views([leg], price_resolver=MidPriceResolver()), None)
    quote_age = leg_view.quote_age if leg_view else safe_float(leg.get("quote_age_sec"))
    mid_source = leg_view.mid_source if leg_view else None
    one_sided = bool(leg.get("one_sided"))
    return _LegSummary(
        strike=strike,
        expiry=expiry,
        right=right,
        position=signed_position,
        qty=qty,
        bid=bid,
        ask=ask,
        min_tick=min_tick_value,
        quote_age_sec=quote_age,
        mid_source=mid_source,
        one_sided=one_sided,
    )


def _evaluate_combo_structure(
    legs: Sequence[dict],
) -> tuple[str | None, float | None, list[_LegSummary]]:
    """Validate combo structure and return (structure_type, width, summaries)."""

    summaries = [_normalize_leg_summary(leg) for leg in legs]
    expiries = {item.expiry for item in summaries}
    if len(expiries) > 1:
        _block_order("expiry_mismatch", "alle legs moeten dezelfde expiratiedatum hebben")

    if len(summaries) == 2:
        rights = {item.right for item in summaries}
        if len(rights) != 1:
            _block_order("unsupported_structure", "vertical spread moet gelijke rechten hebben")
        shorts = [leg for leg in summaries if leg.is_short]
        longs = [leg for leg in summaries if leg.is_long]
        if len(shorts) != 1 or len(longs) != 1:
            _block_order("vertical_parity", "vertical spread vereist één short en één long leg")
        short_leg = shorts[0]
        long_leg = longs[0]
        width = abs(short_leg.strike - long_leg.strike)
        if width <= 0:
            _block_order("invalid_width", "spread breedte kan niet nul zijn")
        if short_leg.right == "call" and not (short_leg.strike < long_leg.strike):
            _block_order(
                "delta_sanity",
                "call vertical: short strike moet lager zijn dan long strike",
            )
        if short_leg.right == "put" and not (short_leg.strike > long_leg.strike):
            _block_order(
                "delta_sanity",
                "put vertical: short strike moet hoger zijn dan long strike",
            )
        return "vertical", width, summaries

    if len(summaries) == 4:
        rights = {item.right for item in summaries}
        if rights != {"call", "put"}:
            _block_order("unsupported_structure", "iron condor/fly vereist zowel calls als puts")
        calls = [item for item in summaries if item.right == "call"]
        puts = [item for item in summaries if item.right == "put"]
        if len(calls) != 2 or len(puts) != 2:
            _block_order("iron_parity", "iron structuur vereist twee calls en twee puts")
        call_long = next((leg for leg in calls if leg.is_long), None)
        call_short = next((leg for leg in calls if leg.is_short), None)
        put_long = next((leg for leg in puts if leg.is_long), None)
        put_short = next((leg for leg in puts if leg.is_short), None)
        if not all([call_long, call_short, put_long, put_short]):
            _block_order("iron_parity", "longs horen op de wings, shorts in het midden")
        if not (call_long.strike > call_short.strike):
            _block_order(
                "delta_sanity",
                "call wing moet verder uit de money liggen dan de short call",
            )
        if not (put_long.strike < put_short.strike):
            _block_order(
                "delta_sanity",
                "put wing moet verder uit de money liggen dan de short put",
            )
        ordered = sorted(summaries, key=lambda item: (item.strike, item.right))
        if ordered[0].is_short or ordered[-1].is_short:
            _block_order("iron_parity", "wings moeten long zijn")
        middle = ordered[1:3]
        if any(item.is_long for item in middle):
            _block_order("iron_parity", "middenbenen moeten short zijn")
        if not (ordered[0].strike < ordered[1].strike <= ordered[2].strike < ordered[3].strike):
            _block_order("delta_sanity", "strikes staan niet in oplopende volgorde voor iron structuur")
        call_width = call_long.strike - call_short.strike
        put_width = put_short.strike - put_long.strike
        if call_width <= 0 or put_width <= 0:
            _block_order("invalid_width", "spread breedte ongeldig voor iron structuur")
        width = min(call_width, put_width)
        structure = "iron_fly" if math.isclose(call_short.strike, put_short.strike) else "iron_condor"
        return structure, width, summaries

    return None, None, summaries


def _collect_min_tick(legs: Sequence[_LegSummary]) -> float | None:
    values = [
        float(leg.min_tick)
        for leg in legs
        if leg.min_tick not in (None, 0)
    ]
    if not values:
        return None
    return min(value for value in values if value > 0)


def _combo_leg_ratio(leg: _LegSummary, combo_quantity: int) -> int:
    qty = abs(int(getattr(leg, "qty", 0) or 0))
    if qty <= 0:
        return 1
    if combo_quantity <= 0:
        return qty
    ratio = qty // combo_quantity
    if ratio <= 0:
        ratio = 1
    return ratio


def _compute_combo_nbbo(
    legs: Sequence[_LegSummary],
    combo_quantity: int,
    *,
    min_tick: float | None,
) -> ComboQuote | None:
    if not legs:
        return None
    combo_bid = 0.0
    combo_ask = 0.0
    for leg in legs:
        if leg.bid is None or leg.ask is None:
            return None
        if leg.bid <= 0 or leg.ask <= 0:
            return None
        if leg.one_sided:
            return None
        ratio = _combo_leg_ratio(leg, combo_quantity)
        if leg.is_short:
            combo_bid += leg.bid * ratio
            combo_ask += leg.ask * ratio
        else:
            combo_bid -= leg.ask * ratio
            combo_ask -= leg.bid * ratio
    bid_val = abs(combo_bid)
    ask_val = abs(combo_ask)
    low, high = sorted((bid_val, ask_val))
    width = high - low
    if not math.isfinite(width):
        return None
    mid_raw = (low + high) / 2
    if not math.isfinite(mid_raw) or mid_raw <= 0:
        return None
    mid = _round_to_tick(mid_raw, min_tick=min_tick)
    if mid <= 0:
        return None
    return ComboQuote(bid=low, ask=high, mid=mid, width=width)


def _evaluate_tradeability(
    legs: Sequence[_LegSummary],
    combo_quote: ComboQuote,
) -> tuple[bool, str]:
    for idx, leg in enumerate(legs, start=1):
        if leg.bid is None or leg.ask is None or leg.bid <= 0 or leg.ask <= 0:
            return False, f"leg{idx}_missing_bid_ask"
        if leg.one_sided:
            return False, f"leg{idx}_one_sided"
    if combo_quote.width < 0:
        return False, "combo_width_negative"
    if combo_quote.mid <= 0:
        return False, "combo_mid_non_positive"
    threshold = max(
        _COMBO_SPREAD_ABS_THRESHOLD,
        combo_quote.mid * _COMBO_SPREAD_REL_THRESHOLD,
    )
    if combo_quote.width > threshold + 1e-9:
        return False, f"combo_spread_wide={combo_quote.width:.2f}>{threshold:.2f}"
    for idx, leg in enumerate(legs, start=1):
        age = leg.quote_age_sec
        if age is None or age > _COMBO_MAX_QUOTE_AGE_SEC:
            return False, f"stale_quote_leg{idx}"
    for idx, leg in enumerate(legs, start=1):
        source = (leg.mid_source or "").strip().lower()
        if reason_from_mid_source(source) is not None:
            return False, f"mid_source_leg{idx}={source}"
    return True, f"(spread={combo_quote.width:.2f} ≤ {threshold:.2f})"


def _orders_active_without_fill(app: OrderPlacementApp, order_ids: Sequence[int]) -> bool:
    if not order_ids:
        return False
    active_statuses = {"Submitted", "PreSubmitted"}
    for order_id in order_ids:
        event = getattr(app, "_order_events", {}).get(order_id)
        if not isinstance(event, dict):
            return False
        status = str(event.get("status") or "").strip()
        if status not in active_statuses:
            return False
        filled = safe_float(event.get("filled"))
        if filled not in (None, 0):
            return False
        remaining = safe_float(event.get("remaining"))
        if remaining == 0:
            return False
    return True


def _reprice_single_instruction(instr: OrderInstruction) -> bool:
    if not instr.legs:
        return False
    order = instr.order
    try:
        combo_quantity = int(getattr(order, "totalQuantity", 0) or 0)
    except Exception:
        combo_quantity = 0
    if combo_quantity <= 0:
        combo_quantity = 1
    _, combo_width, summaries = _evaluate_combo_structure(instr.legs)
    min_tick = instr.min_tick
    if not min_tick:
        min_tick = _collect_min_tick(summaries)
    nbbo = _compute_combo_nbbo(summaries, combo_quantity, min_tick=min_tick)
    if nbbo is None:
        log.info("[repricer] skipped (nbbo_unavailable)")
        return False
    ok, gate_message = _evaluate_tradeability(summaries, nbbo)
    if not ok:
        log.info(f"[repricer] gate failed ({gate_message}) -> skip repricing")
        return False
    tick = min_tick or 0.01
    if tick <= 0:
        tick = 0.01
    current_limit = safe_float(getattr(order, "lmtPrice", None))
    if current_limit is None or current_limit <= 0:
        return False
    epsilon = max(0.05, 2 * tick)
    width_cap = None
    if combo_width is not None:
        width_cap = max(combo_width - epsilon, 0.0)
    action = str(getattr(order, "action", "") or "").upper()
    if action == "BUY":
        candidate = max(current_limit - tick, nbbo.bid)
        if width_cap is not None and candidate > width_cap and width_cap >= nbbo.bid:
            candidate = width_cap
        if candidate >= current_limit - 1e-9:
            return False
    else:
        candidate = min(current_limit + tick, nbbo.ask)
        if width_cap is not None and candidate > width_cap:
            candidate = width_cap
        if candidate <= current_limit + 1e-9:
            return False
    new_limit = _round_to_tick(candidate, min_tick=min_tick)
    if new_limit <= 0 or abs(new_limit - current_limit) < tick / 2:
        return False
    order.lmtPrice = new_limit
    instr.combo_quote = nbbo
    instr.min_tick = min_tick
    instr.combo_width = combo_width
    instr.epsilon = epsilon
    log.info(f"[repricer] 10s no fill → new limit={new_limit:.2f}")
    return True


def _attempt_reprice_if_needed(
    app: OrderPlacementApp,
    instructions: Sequence[OrderInstruction],
    placed_ids: Sequence[int],
) -> bool:
    if not instructions or not placed_ids:
        return False
    if not _orders_active_without_fill(app, placed_ids):
        return False
    wait_time = max(_REPRICER_WAIT_SECONDS, 0)
    if wait_time:
        log.info("[repricer] waiting %ss for fill before adjusting", int(wait_time))
        time.sleep(wait_time)
    if not _orders_active_without_fill(app, placed_ids):
        log.info("[repricer] skip repricer; order updated during wait")
        return False
    updated = False
    for instr in instructions:
        if _reprice_single_instruction(instr):
            updated = True
    if not updated:
        return False
    for order_id in placed_ids:
        try:
            app.cancelOrder(order_id)
        except Exception:  # pragma: no cover - defensive
            logger.debug("Kon order niet annuleren tijdens repricer", exc_info=True)
    return True


def _compute_worst_case_credit(
    legs: Sequence[_LegSummary],
    *,
    combo_quantity: int,
) -> float | None:
    worst_value: float | None = 0.0
    for leg in legs:
        ratio = max(1, int(abs(leg.qty) // max(combo_quantity, 1)))
        if leg.is_short:
            if leg.bid is None:
                return None
            worst_value += leg.bid * ratio
        else:
            if leg.ask is None:
                return None
            worst_value -= leg.ask * ratio
    if worst_value is None:
        return None
    return worst_value * 100


def _round_to_tick(price: float, *, min_tick: float | None) -> float:
    if min_tick in (None, 0):
        return round(price + 1e-9, 2)
    try:
        tick = Decimal(str(min_tick))
        value = Decimal(str(price))
    except Exception:  # pragma: no cover - defensive fallback
        return round(price + 1e-9, 2)
    steps = (value / tick).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    rounded = steps * tick
    return float(rounded)


def _guard_limit_price_scale(order: Order, *, credit_for_scale: float | None) -> None:
    """Abort order creation when price and credit look mismatched in scale."""

    if credit_for_scale is None:
        return
    price = getattr(order, "lmtPrice", None)
    if price is None:
        return
    try:
        price_val = float(price)
        credit_val = float(credit_for_scale)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return
    if abs(price_val) < 1 and abs(credit_val) > 100:
        _block_order("scale_mismatch", "verkeerde schaal")


def _has_non_guaranteed(order: Order) -> bool:
    """Return ``True`` if the order requests ``NonGuaranteed`` routing."""

    params = getattr(order, "smartComboRoutingParams", None)
    if not params:
        return False
    try:
        iterator = list(params)
    except TypeError:  # pragma: no cover - defensive
        return False
    for param in iterator:
        tag = getattr(param, "tag", None)
        value = getattr(param, "value", None)
        if str(tag or "").lower() == "nonguaranteed" and str(value) == "1":
            return True
    return False


def _clear_non_guaranteed(order: Order) -> None:
    """Remove any ``NonGuaranteed`` routing parameter from ``order``."""

    params = getattr(order, "smartComboRoutingParams", None)
    if not params:
        order.smartComboRoutingParams = []
        return
    try:
        filtered = [
            param
            for param in params
            if str(getattr(param, "tag", "")).lower() != "nonguaranteed"
        ]
    except TypeError:  # pragma: no cover - defensive
        filtered = []
    order.smartComboRoutingParams = filtered


def _should_request_non_guaranteed(order: Order, contract: Contract) -> bool:
    """Return ``True`` when ``NonGuaranteed`` routing is allowed for this order."""

    exchange = str(getattr(contract, "exchange", "") or "").upper()
    if exchange != "SMART":
        return False
    combo_legs = getattr(contract, "comboLegs", None) or []
    if len(combo_legs) != 2:
        return False
    order_type = str(getattr(order, "orderType", "") or "").upper()
    if order_type == "LMT":
        return False
    return True


def _force_directed_exchange(contract: Contract, exchanges: Sequence[str] = ("CBOE", "BOX")) -> str:
    """Update ``contract`` and combo legs to use a directed exchange."""

    current = str(getattr(contract, "exchange", "") or "").upper()
    target = None
    for candidate in exchanges:
        candidate = candidate.upper()
        if candidate != current:
            target = candidate
            break
    if target is None:
        target = exchanges[0].upper() if exchanges else "CBOE"
    try:
        contract.exchange = target
    except Exception:  # pragma: no cover - defensive
        pass
    try:
        contract.primaryExchange = target
    except Exception:  # pragma: no cover - defensive
        pass
    combo_legs = getattr(contract, "comboLegs", None) or []
    for combo_leg in combo_legs:
        try:
            combo_leg.exchange = target
        except Exception:  # pragma: no cover - defensive
            continue
    return target


def _infer_combo_width(proposal: StrategyProposal, legs: Sequence[dict]) -> float | None:
    """Return maximum spread width (per contract) inferred from legs or proposal."""

    widths: list[float] = []
    wing_width = getattr(proposal, "wing_width", None)
    if wing_width:
        try:
            for value in wing_width.values():
                if value is None:
                    continue
                widths.append(abs(float(value)))
        except Exception:  # pragma: no cover - defensive
            widths = []
    if not widths:
        strikes_by_type: dict[str, list[float]] = {}
        for leg in legs:
            try:
                strike = leg.get("strike")
                right = get_leg_right(leg)
                if strike in (None, "") or right not in {"call", "put"}:
                    continue
                strikes_by_type.setdefault(right, []).append(float(strike))
            except Exception:
                continue
        for strike_values in strikes_by_type.values():
            if len(strike_values) < 2:
                continue
            low = min(strike_values)
            high = max(strike_values)
            widths.append(abs(high - low))
    if not widths:
        return None
    max_width = max(widths)
    if max_width <= 0:
        return None
    return max_width


@dataclass
class OrderInstruction:
    """Single IB order structure derived from one or more legs."""

    contract: Contract
    order: Order
    legs: list[dict]
    credit_per_combo: float | None = None
    combo_quote: ComboQuote | None = None
    min_tick: float | None = None
    combo_width: float | None = None
    epsilon: float | None = None


def _validate_instructions(instructions: Sequence[OrderInstruction]) -> None:
    """Validate order instructions before submission."""

    for instr in instructions:
        contract = getattr(instr, "contract", None)
        order = getattr(instr, "order", None)
        if contract is None or order is None:
            continue
        sec_type = str(getattr(contract, "secType", "") or "").upper()
        if sec_type != "BAG":
            continue
        combo_legs = getattr(contract, "comboLegs", None) or []
        if len(combo_legs) > 2 and _has_non_guaranteed(order):
            raise ValueError(
                "NonGuaranteed routing is niet toegestaan voor BAG-combo's met meer dan twee benen"
            )
        credit = getattr(instr, "credit_per_combo", None)
        action = str(getattr(order, "action", "") or "").upper()
        if credit is not None and action in {"BUY", "SELL"}:
            if (action == "BUY" and credit < 0) or (action == "SELL" and credit > 0):
                raise ValueError("Inconsistent combo direction vs credit/debit")


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
        self._order_errors: dict[int, list[tuple[int, str]]] = {}
        self._contract_details_events: dict[int, bool] = {}
        self._validated_conids: set[int] = set()
        self._contract_details_end: set[int] = set()
        self._contract_details_req_map: dict[int, int] = {}
        self._next_contract_details_req_id = 10_000
        self._lock = None
        self.next_order_id_ready = False

    # IB callbacks -------------------------------------------------
    def error(  # type: ignore[override]
        self,
        reqId: int,
        errorTime: int,
        errorCode: int,
        errorString: str,
        advancedOrderRejectJson: str = "",
    ) -> None:
        super().error(reqId, errorTime, errorCode, errorString, advancedOrderRejectJson)
        try:
            order_id = int(reqId)
        except (TypeError, ValueError):
            return
        if order_id < 0:
            return
        errors = self._order_errors.setdefault(order_id, [])
        errors.append((int(errorCode), str(errorString)))

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
                if self._order_errors.get(order_id):
                    logger.debug(
                        "❗ Order %s ontving een foutmelding: %s",
                        order_id,
                        self._order_errors.get(order_id),
                    )
                    return

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

    # Helpers ------------------------------------------------------
    def get_order_errors(
        self, order_ids: Sequence[int] | None = None
    ) -> list[tuple[int, int, str]]:
        if order_ids is None:
            items = self._order_errors.items()
        else:
            items = ((order_id, self._order_errors.get(order_id, [])) for order_id in order_ids)
        collected: list[tuple[int, int, str]] = []
        for order_id, errors in items:
            for code, message in errors:
                collected.append((int(order_id), int(code), str(message)))
        return collected


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
            position = get_signed_position(leg)
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
                exchange=str(leg.get("exchange") or cfg_value("OPTIONS_EXCHANGE", "SMART")),
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
            order.orderType = (order_type or cfg_value("DEFAULT_ORDER_TYPE", "LMT")).upper()
            order.tif = (tif or cfg_value("DEFAULT_TIME_IN_FORCE", "DAY")).upper()
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

        structure, combo_width, leg_summaries = _evaluate_combo_structure(legs)
        min_tick = _collect_min_tick(leg_summaries)
        epsilon = 0.05
        if min_tick and min_tick > 0:
            epsilon = max(0.05, 2 * min_tick)
        combo_quote = _compute_combo_nbbo(
            leg_summaries,
            combo_quantity,
            min_tick=min_tick,
        )
        if combo_quote is None:
            proposal.order_preview_only = True
            proposal.tradeability_notes = "combo_nbbo_unavailable"
            log.info("[nbbo] unavailable -> proposal advisory only")
            raise ValueError("combo heeft geen betrouwbare NBBO")
        log.info(
            "[nbbo] bid=%.2f mid=%.2f ask=%.2f width=%.2f",
            combo_quote.bid,
            combo_quote.mid,
            combo_quote.ask,
            combo_quote.width,
        )
        gate_ok, gate_message = _evaluate_tradeability(leg_summaries, combo_quote)
        if not gate_ok:
            proposal.order_preview_only = True
            proposal.tradeability_notes = gate_message
            log.info(f"[gate] failed ({gate_message}) -> proposal advisory only")
            raise ValueError(f"combo niet verhandelbaar: {gate_message}")
        proposal.order_preview_only = False
        proposal.tradeability_notes = gate_message
        log.info(f"[gate] ok {gate_message}")
        order = Order()
        order.totalQuantity = combo_quantity
        net_credit = proposal.credit
        if net_credit is None:
            net_credit = calculate_credit(legs)
        mid_credit = _combo_mid_credit(legs)
        per_combo_credit = None
        per_combo_mid_credit: float | None = None
        if net_credit is not None:
            try:
                per_combo_credit = net_credit / max(combo_quantity, 1)
            except Exception:
                per_combo_credit = net_credit
        if mid_credit is not None:
            try:
                per_combo_mid_credit = mid_credit / max(combo_quantity, 1)
            except Exception:
                per_combo_mid_credit = mid_credit
        credit_reference = per_combo_credit
        if credit_reference is None:
            credit_reference = per_combo_mid_credit
        if credit_reference is None:
            _block_order("missing_credit", "combo mist (mid) credit informatie")
        net_price = combo_quote.mid
        price_capped = False
        if combo_width is not None:
            width_cap = combo_width - epsilon
            if width_cap <= 0:
                _block_order("price_too_close_to_width", "spread breedte laat geen veilige limit toe")
            if per_combo_credit is not None and abs(float(per_combo_credit)) / 100.0 > width_cap + 1e-9:
                _block_order(
                    "price_too_close_to_width",
                    "contract credit groter dan spread breedte minus marge",
                )
            if net_price > width_cap:
                net_price = width_cap
                price_capped = True
        net_price = _round_to_tick(net_price, min_tick=min_tick)
        if combo_width is not None and net_price > combo_width - epsilon + 1e-9:
            price_capped = True
            capped_to = max(combo_width - epsilon, 0)
            net_price = _round_to_tick(capped_to, min_tick=min_tick)
        if net_price <= 0:
            _block_order("tick_rounding_underflow", "limit price valt naar nul na afronding")
        if credit_reference is not None:
            credit_price = abs(float(credit_reference)) / 100.0
            allowed_diff = max(min_tick or 0.01, epsilon if combo_width is not None else 0.05)
            if abs(credit_price - net_price) > allowed_diff + 1e-9:
                _block_order(
                    "credit_limit_mismatch",
                    f"limit {net_price:.2f} wijkt teveel af van credit {credit_price:.2f}",
                )
        order.orderType = "LMT"
        order.algoStrategy = ""
        order.algoParams = []
        if _should_request_non_guaranteed(order, combo_contract):
            order.smartComboRoutingParams = [TagValue("NonGuaranteed", "1")]
        else:
            order.smartComboRoutingParams = []
        order.tif = (tif or cfg_value("DEFAULT_TIME_IN_FORCE", "DAY")).upper()
        if hasattr(order, "lmtPrice"):
            order.lmtPrice = float(net_price)
            _guard_limit_price_scale(order, credit_for_scale=credit_reference)
        worst_credit = _compute_worst_case_credit(
            leg_summaries,
            combo_quantity=combo_quantity,
        )
        if (
            worst_credit is not None
            and credit_reference is not None
            and worst_credit * credit_reference < 0
        ):
            _block_order(
                "direction_vs_cash_mismatch",
                "combo credit en legs cashflow spreken elkaar tegen",
            )
        action = "BUY" if credit_reference > 0 else "SELL"
        if price_capped:
            log.info("price_capped_to=%.2f", net_price)
        width_display = combo_width
        if width_display is None:
            width_display = _infer_combo_width(proposal, legs)
        width_str = "n/a"
        if width_display is not None and width_display > 0:
            width_str = f"{width_display:.2f}"
        credit_price = float(credit_reference) / 100.0
        lmt_display = f"{float(net_price):.2f}"
        capped_suffix = " (capped)" if price_capped else ""
        log.info(
            "[order-check] credit=%+0.2f → action=%s | width=%s | eps=%0.2f | lmt=%s%s",
            credit_price,
            action,
            width_str,
            epsilon,
            lmt_display,
            capped_suffix,
        )
        order.action = action
        order.transmit = True
        order.account = account or "DUK809533"
        order.orderRef = f"{proposal.strategy}-{symbol}"
        return [
            OrderInstruction(
                contract=combo_contract,
                order=order,
                legs=list(legs),
                credit_per_combo=credit_reference,
                combo_quote=combo_quote,
                min_tick=min_tick,
                combo_width=combo_width,
                epsilon=epsilon,
            )
        ]

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

        instructions = list(instructions)
        _validate_instructions(instructions)

        retry_info: dict[str, Any] | None = None
        directed_retry_done = False
        repricer_done = False

        attempt = 0
        while True:
            attempt += 1
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
                order_map: dict[int, OrderInstruction] = {}
                for idx, instr in enumerate(instructions):
                    current_id = order_id + idx
                    order = instr.order
                    order_map[current_id] = instr
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
                    log.info(
                        "orderType=%s algoStrategy=%s smartComboRoutingParams=%s",
                        getattr(order, "orderType", ""),
                        getattr(order, "algoStrategy", ""),
                        getattr(order, "smartComboRoutingParams", None),
                    )
                    app.placeOrder(current_id, instr.contract, order)
                    placed_ids.append(current_id)
                app.wait_for_order_handshake(placed_ids)
                errors = app.get_order_errors(placed_ids)
                retryable = False
                for err_order_id, code, _message in errors:
                    if code != 10043:
                        continue
                    instr = order_map.get(err_order_id)
                    if instr and _has_non_guaranteed(instr.order):
                        retryable = True
                        break
                if retryable:
                    if retry_info is not None:
                        logger.error(
                            "IB error 10043 blijft optreden ondanks het verwijderen van NonGuaranteed"
                        )
                        raise RuntimeError(
                            "IB error 10043: combo-order geweigerd nadat NonGuaranteed werd verwijderd"
                        )
                    retry_info = {
                        "reason": "remove_non_guaranteed_for_multi_leg_combo",
                        "old_ids": tuple(placed_ids),
                    }
                    logger.warning(
                        "⚠️ IB error 10043 ontvangen voor order(s) %s; probeer opnieuw zonder NonGuaranteed",
                        ", ".join(map(str, placed_ids)),
                    )
                    for instr in instructions:
                        if _has_non_guaranteed(instr.order):
                            _clear_non_guaranteed(instr.order)
                    _validate_instructions(instructions)
                    try:
                        app.disconnect()
                    except Exception:
                        logger.debug(
                            "Kon app niet disconnecten na IB fout", exc_info=True
                        )
                    continue

                directed_exchange_needed = False
                for _err_order_id, code, _message in errors:
                    if code == 201 and not directed_retry_done:
                        directed_exchange_needed = True
                        break
                if directed_exchange_needed:
                    directed_retry_done = True
                    retry_info = {
                        "reason": "directed_exchange_after_201",
                        "old_ids": tuple(placed_ids),
                    }
                    chosen_exchange: str | None = None
                    for instr in instructions:
                        chosen_exchange = _force_directed_exchange(instr.contract)
                    if chosen_exchange:
                        logger.warning(
                            "⚠️ IB error 201 ontvangen; herprobeer met exchange=%s",
                            chosen_exchange,
                        )
                    else:
                        logger.warning("⚠️ IB error 201 ontvangen; herprobeer met directed exchange")
                    _validate_instructions(instructions)
                    try:
                        app.disconnect()
                    except Exception:
                        logger.debug("Kon app niet disconnecten na IB fout", exc_info=True)
                    continue

                if not repricer_done:
                    if _attempt_reprice_if_needed(app, instructions, placed_ids):
                        repricer_done = True
                        retry_info = {
                            "reason": "repricer_adjustment",
                            "old_ids": tuple(placed_ids),
                        }
                        try:
                            app.disconnect()
                        except Exception:
                            logger.debug(
                                "Kon app niet disconnecten na repricer", exc_info=True
                            )
                        continue

                if retry_info:
                    old_ids = retry_info.get("old_ids", ())
                    mapping = ", ".join(
                        f"{old} -> {new}" for old, new in zip(old_ids, placed_ids)
                    )
                    if not mapping:
                        mapping = (
                            f"old_order_ids={list(old_ids)} new_order_ids={placed_ids}"
                        )
                    logger.info(
                        "retry_reason=%s %s",
                        retry_info.get("reason", "unknown"),
                        mapping,
                    )
                return app, placed_ids
            except Exception:
                logger.exception("❌ Fout bij versturen van IB orders")
                try:
                    app.disconnect()
                except Exception:
                    logger.debug("Kon app niet disconnecten na uitzondering", exc_info=True)
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

