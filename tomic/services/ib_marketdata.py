"""Interactive Brokers market data refresh helpers."""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from pprint import pformat
from typing import Any, Callable, Mapping

try:  # pragma: no cover - optional dependency during tests
    from ibapi.ticktype import TickTypeEnum
except Exception:  # pragma: no cover
    class TickTypeEnum:  # type: ignore[too-many-ancestors]
        BID = 1
        ASK = 2
        LAST = 4
        CLOSE = 9

try:  # pragma: no cover - ``ibapi`` optional in tests
    from ibapi.contract import Contract
except Exception:  # pragma: no cover
    Contract = object  # type: ignore[assignment]

from tomic.api.base_client import BaseIBApp
from tomic.api.ib_connection import connect_ib
from tomic.analysis import scoring
from tomic.config import get as cfg_get
from tomic.logutils import logger
from tomic.models import OptionContract
from tomic.services.strategy_pipeline import StrategyProposal
from tomic.utils import get_leg_qty, get_leg_right, normalize_leg


_GENERIC_TICKS = "100,101,104,106"


def _cfg(key: str, default: Any) -> Any:
    value = cfg_get(key, default)
    return default if value in {None, ""} else value


def _parse_expiry(value: str | None) -> str:
    if not value:
        raise ValueError("Missing expiry")
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if len(digits) == 6:  # YYMMDD -> prefix 20
        digits = "20" + digits
    if len(digits) != 8:
        raise ValueError(f"Unsupported expiry format: {value}")
    return digits


def _normalize_symbol(leg: Mapping[str, Any]) -> str:
    symbol = (
        leg.get("symbol")
        or leg.get("underlying")
        or leg.get("ticker")
        or leg.get("root")
        or leg.get("root_symbol")
    )
    if not symbol:
        raise ValueError("Leg mist onderliggende ticker")
    return str(symbol).upper()


def _loggable_leg_payload(leg: Mapping[str, Any]) -> dict[str, Any]:
    """Return a trimmed view of ``leg`` for logging purposes."""

    keys = (
        "symbol",
        "underlying",
        "expiry",
        "strike",
        "type",
        "right",
        "position",
        "qty",
        "exchange",
        "currency",
        "multiplier",
        "tradingClass",
        "trading_class",
        "primaryExchange",
        "primary_exchange",
        "conId",
        "con_id",
    )
    snapshot: dict[str, Any] = {
        key: leg[key]
        for key in keys
        if key in leg and leg[key] not in (None, "")
    }
    extras = {
        key: leg[key]
        for key in leg
        if key not in snapshot and key not in keys
    }
    if extras:
        snapshot["extras"] = {
            key: extras[key]
            for key in sorted(extras)
        }
    return snapshot


@dataclass
class SnapshotResult:
    """Outcome of a quote refresh operation."""

    proposal: StrategyProposal
    reasons: list[Any]
    accepted: bool
    missing_quotes: list[str]


class QuoteSnapshotApp(BaseIBApp):
    """Light-weight IB client for market data snapshots."""

    WARNING_ERROR_CODES: set[int] = BaseIBApp.WARNING_ERROR_CODES | {2104, 2106, 2158}

    def __init__(self) -> None:
        super().__init__()
        self._req_id = 5000
        self._responses: dict[int, dict[str, Any]] = {}
        self._events: dict[int, threading.Event] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _next_id(self) -> int:
        with self._lock:
            self._req_id += 1
            return self._req_id

    def _event(self, req_id: int) -> threading.Event:
        return self._events.setdefault(req_id, threading.Event())

    def _data(self, req_id: int) -> dict[str, Any]:
        return self._responses.setdefault(req_id, {})

    # ------------------------------------------------------------------
    # IB callbacks
    # ------------------------------------------------------------------
    def tickPrice(self, reqId: int, tickType: int, price: float, attrib: Any) -> None:  # noqa: N802 - IB API
        data = self._data(reqId)
        if tickType == TickTypeEnum.BID:
            data["bid"] = price
        elif tickType == TickTypeEnum.ASK:
            data["ask"] = price
        elif tickType == TickTypeEnum.LAST:
            data["last"] = price
        elif tickType == TickTypeEnum.CLOSE:
            data.setdefault("last", price)
        if not math.isnan(price):
            self._event(reqId).set()

    def tickSnapshotEnd(self, reqId: int) -> None:  # noqa: N802 - IB API
        self._event(reqId).set()

    def tickOptionComputation(
        self,
        reqId: int,
        tickType: int,
        impliedVol: float,
        delta: float,
        optPrice: float,
        pvDividend: float,
        gamma: float,
        vega: float,
        theta: float,
        undPrice: float,
    ) -> None:  # noqa: N802 - IB API
        data = self._data(reqId)
        if not math.isnan(delta):
            data["delta"] = delta
        if not math.isnan(gamma):
            data["gamma"] = gamma
        if not math.isnan(vega):
            data["vega"] = vega
        if not math.isnan(theta):
            data["theta"] = theta
        if not math.isnan(impliedVol):
            data["iv"] = impliedVol

    def error(self, reqId: int, errorTime: int, errorCode: int, errorString: str, advancedOrderRejectJson: str = "") -> None:  # noqa: N802 - IB API
        super().error(reqId, errorTime, errorCode, errorString, advancedOrderRejectJson)
        if reqId > 0:
            self._event(reqId).set()


class IBMarketDataService:
    """High level orchestration for refreshing proposal quotes."""

    def __init__(
        self,
        *,
        app_factory: Callable[[], QuoteSnapshotApp] | None = None,
        generic_ticks: str | None = None,
        use_snapshot: bool | None = None,
    ) -> None:
        self._app_factory = app_factory or QuoteSnapshotApp
        cfg_ticks = (
            generic_ticks
            if generic_ticks is not None
            else _cfg("MKT_GENERIC_TICKS", _GENERIC_TICKS)
        )
        if isinstance(cfg_ticks, str):
            cfg_ticks = cfg_ticks.strip()
        self._generic_ticks = cfg_ticks or ""
        if use_snapshot is None:
            use_snapshot = bool(_cfg("IB_USE_SNAPSHOT_DATA", True))
        self._use_snapshot = bool(use_snapshot)

    def _should_use_snapshot(self) -> bool:
        """Return ``True`` when snapshot requests can be used safely."""

        return self._use_snapshot and not bool(self._generic_ticks)

    # ------------------------------------------------------------------
    def refresh(
        self,
        proposal: StrategyProposal,
        *,
        criteria: Any | None = None,
        spot_price: float | None = None,
        interest_rate: float | None = None,
        timeout: float | None = None,
    ) -> SnapshotResult:
        if not proposal.legs:
            return SnapshotResult(proposal, [], True, [])

        timeout = timeout or float(_cfg("MARKET_DATA_TIMEOUT", 15))
        port = int(_cfg("IB_PORT", 7497))
        if bool(_cfg("IB_PAPER_MODE", True)):
            port = int(_cfg("IB_PORT", 7497))
        else:
            port = int(_cfg("IB_LIVE_PORT", 7496))
        client_id = int(_cfg("IB_MARKETDATA_CLIENT_ID", 901))
        host = str(_cfg("IB_HOST", "127.0.0.1"))

        app = self._app_factory()
        logger.info("📡 Ophalen IB quotes voor voorstel")
        connect_ib(
            client_id=client_id,
            host=host,
            port=port,
            timeout=int(timeout),
            app=app,
        )

        try:
            missing: list[str] = []
            generic_ticks = self._generic_ticks or ""
            use_snapshot = self._should_use_snapshot()
            if self._use_snapshot and not use_snapshot:
                logger.debug(
                    "Snapshot market data not supported with generic ticks %s; using streaming data instead",
                    generic_ticks,
                )
            for leg in proposal.legs:
                try:
                    contract = self._build_contract(leg)
                except Exception as exc:
                    logger.warning(f"⚠️ Contract kon niet worden opgebouwd: {exc}")
                    logger.warning(
                        "IB leg payload bij fout: %s",
                        pformat(_loggable_leg_payload(leg)),
                    )
                    missing.append(str(leg.get("strike")))
                    leg["missing_edge"] = True
                    continue
                req_id = app._next_id()
                event = app._event(req_id)
                logger.debug(
                    "reqMktData req_id=%s symbol=%s strike=%s right=%s", req_id, contract.symbol, getattr(contract, "strike", "-"), getattr(contract, "right", "-")
                )
                app.reqMktData(req_id, contract, generic_ticks, use_snapshot, False, [])
                if not event.wait(timeout):
                    logger.warning(
                        "⏱ Timeout bij ophalen quote voor strike %s", leg.get("strike")
                    )
                    missing.append(str(leg.get("strike")))
                    leg["missing_edge"] = True
                else:
                    snapshot = app._responses.get(req_id, {})
                    self._apply_snapshot(leg, snapshot)
                    if not snapshot:
                        missing.append(str(leg.get("strike")))
                        leg["missing_edge"] = True
                try:
                    app.cancelMktData(req_id)
                except Exception:
                    pass

            score, reasons = scoring.calculate_score(
                proposal.strategy,
                proposal,
                spot=spot_price,
                criteria=criteria,
                atr=proposal.atr,
            )
            accepted = score is not None
            return SnapshotResult(proposal, reasons, accepted, missing)
        finally:
            try:
                app.disconnect()
            except Exception:
                logger.debug("Kon IB verbinding niet netjes sluiten", exc_info=True)

    # ------------------------------------------------------------------
    def _build_contract(self, leg: Mapping[str, Any]) -> Contract:
        symbol = _normalize_symbol(leg)
        expiry = _parse_expiry(str(leg.get("expiry")))
        strike = float(leg.get("strike"))
        right = get_leg_right(leg)
        if right not in {"call", "put"}:
            raise ValueError("Onbekend optietype")
        info = OptionContract(
            symbol=symbol,
            expiry=expiry,
            strike=strike,
            right=right[:1].upper(),
            exchange=str(leg.get("exchange") or _cfg("OPTIONS_EXCHANGE", "SMART")),
            currency=str(leg.get("currency") or "USD"),
            multiplier=str(leg.get("multiplier") or "100"),
            trading_class=leg.get("tradingClass") or leg.get("trading_class"),
            primary_exchange=leg.get("primaryExchange") or leg.get("primary_exchange"),
            con_id=leg.get("conId") or leg.get("con_id"),
        )
        contract = info.to_ib()
        return contract

    def _apply_snapshot(self, leg: Mapping[str, Any], data: Mapping[str, Any]) -> None:
        if not isinstance(leg, dict):
            raise TypeError("Leg moet mutable mapping zijn")
        leg.update({k: data[k] for k in ("bid", "ask", "last") if k in data})
        for greek in ("delta", "gamma", "vega", "theta", "iv"):
            if greek in data:
                leg[greek] = data[greek]

        bid = leg.get("bid")
        ask = leg.get("ask")
        mid = None
        if isinstance(bid, (int, float)) and isinstance(ask, (int, float)) and ask > 0:
            mid = (float(bid) + float(ask)) / 2
        elif isinstance(leg.get("last"), (int, float)):
            mid = float(leg["last"])
        if mid is not None:
            leg["mid"] = round(mid, 4)
            leg.pop("missing_edge", None)
        else:
            leg["missing_edge"] = True

        quantity = get_leg_qty(leg)
        leg.setdefault("qty", quantity)
        normalize_leg(leg)


def fetch_quote_snapshot(
    proposal: StrategyProposal,
    *,
    criteria: Any | None = None,
    spot_price: float | None = None,
    interest_rate: float | None = None,
    timeout: float | None = None,
    service: IBMarketDataService | None = None,
) -> SnapshotResult:
    """Refresh proposal quotes via IB and recompute metrics."""

    svc = service or IBMarketDataService()
    return svc.refresh(
        proposal,
        criteria=criteria,
        spot_price=spot_price,
        interest_rate=interest_rate,
        timeout=timeout,
    )


__all__ = [
    "SnapshotResult",
    "IBMarketDataService",
    "QuoteSnapshotApp",
    "fetch_quote_snapshot",
]

