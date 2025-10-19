"""Interactive Brokers market data refresh helpers."""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import datetime
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
    from ibapi.contract import Contract, ContractDetails
except Exception:  # pragma: no cover
    Contract = object  # type: ignore[assignment]
    ContractDetails = object  # type: ignore[assignment]

from tomic.api.base_client import BaseIBApp
from tomic.api.ib_connection import connect_ib
from tomic.analysis import scoring
from tomic.logutils import logger
from tomic.models import OptionContract
from tomic.services._config import cfg_value
from tomic.services._id_sequence import IncrementingIdMixin
from tomic.services.portfolio_service import PortfolioService
from tomic.services.strategy_pipeline import StrategyProposal
from tomic.utils import get_leg_qty, get_leg_right, normalize_leg


_GENERIC_TICKS = "100,101,104,106"
def _is_finite_number(value: Any) -> bool:
    try:
        if isinstance(value, bool):  # bool is subclass of int; ignore
            return False
        number = float(value)
    except (TypeError, ValueError):
        return False
    return not math.isnan(number)


def _store_numeric(target: dict[str, Any], key: str, value: Any) -> bool:
    if _is_finite_number(value):
        target[key] = float(value)
        return True
    return False


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
    delta_log: list[dict[str, Any]] = field(default_factory=list)
    trigger: str | None = None
    metrics_delta: dict[str, Any] | None = None
    governance: dict[str, Any] | None = None
    refreshed_at: str | None = None


def _capture_metric_snapshot(proposal: StrategyProposal) -> dict[str, float]:
    """Return numeric metrics for delta logging."""

    keys = ("score", "ev", "rom", "edge", "credit", "max_profit", "max_loss", "pos")
    metrics: dict[str, float] = {}
    for key in keys:
        value = getattr(proposal, key, None)
        try:
            if value is None:
                continue
            metrics[key] = float(value)
        except (TypeError, ValueError):
            continue
    return metrics


def _compute_metric_delta(
    before: Mapping[str, float], after: Mapping[str, float]
) -> dict[str, dict[str, float | None]]:
    """Return structured delta information between two metric snapshots."""

    delta: dict[str, dict[str, float | None]] = {}
    keys = set(before) | set(after)
    for key in sorted(keys):
        previous = before.get(key)
        current = after.get(key)
        if previous is None and current is None:
            continue
        entry: dict[str, float | None] = {
            "before": previous,
            "after": current,
        }
        if previous is not None and current is not None:
            entry["delta"] = round(current - previous, 6)
        delta[key] = entry
    return delta


def _governance_payload(
    proposal: StrategyProposal,
    snapshot: SnapshotResult,
    trigger: str | None,
) -> dict[str, Any]:
    """Build monitoring payload using portfolio and scoring metadata."""

    mid_sources = PortfolioService._mid_sources(proposal)
    payload: dict[str, Any] = {
        "mid_sources": mid_sources,
        "needs_refresh": bool(getattr(proposal, "needs_refresh", False)),
        "trigger": trigger,
        "accepted": snapshot.accepted,
        "reasons": [getattr(reason, "code", str(reason)) for reason in snapshot.reasons],
    }

    missing_metrics: dict[str, Any] = {}
    ignored_metrics: list[str] = []
    for leg in proposal.legs:
        if not isinstance(leg, Mapping):
            continue
        missing = leg.get("missing_metrics")
        if missing:
            strike = str(leg.get("strike"))
            missing_metrics[strike] = list(missing)
        if leg.get("metrics_ignored"):
            ignored_metrics.append(str(leg.get("strike")))
    if missing_metrics:
        payload["missing_metrics"] = missing_metrics
    if ignored_metrics:
        payload["ignored_metrics"] = ignored_metrics

    payload["bid_ask_pct"] = PortfolioService._avg_bid_ask_pct(proposal)
    payload["risk_reward"] = PortfolioService._risk_reward(proposal)
    summary = getattr(proposal, "fallback_summary", None)
    if isinstance(summary, Mapping):
        payload["fallback_summary"] = {
            str(source): int(summary.get(source, 0) or 0) for source in summary
        }

    return payload


class QuoteSnapshotApp(IncrementingIdMixin, BaseIBApp):
    """Light-weight IB client for market data snapshots."""

    WARNING_ERROR_CODES: set[int] = BaseIBApp.WARNING_ERROR_CODES | {2104, 2106, 2158}

    def __init__(self) -> None:
        super().__init__(initial_request_id=5000)
        self._responses: dict[int, dict[str, Any]] = {}
        self._events: dict[int, threading.Event] = {}
        self._lock = threading.Lock()
        self._snapshot_requests: dict[int, bool] = {}
        self._ready = threading.Event()
        self._contract_details: dict[int, list[ContractDetails]] = {}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _event(self, req_id: int) -> threading.Event:
        return self._events.setdefault(req_id, threading.Event())

    def _data(self, req_id: int) -> dict[str, Any]:
        return self._responses.setdefault(req_id, {})

    def register_request(self, req_id: int, *, snapshot: bool) -> None:
        with self._lock:
            if snapshot:
                self._snapshot_requests[req_id] = True
            else:
                self._snapshot_requests.pop(req_id, None)

    def _is_snapshot(self, req_id: int) -> bool:
        with self._lock:
            return self._snapshot_requests.get(req_id, False)

    def _complete_request(self, req_id: int) -> None:
        with self._lock:
            self._snapshot_requests.pop(req_id, None)

    def _finalize_request(self, req_id: int) -> None:
        self._event(req_id).set()
        self._complete_request(req_id)

    def clear_request(self, req_id: int) -> None:
        self._complete_request(req_id)
        self._events.pop(req_id, None)
        self._responses.pop(req_id, None)
        self._contract_details.pop(req_id, None)

    # ------------------------------------------------------------------
    # Ready / metadata helpers
    # ------------------------------------------------------------------
    def nextValidId(self, orderId: int) -> None:  # noqa: N802 - IB API
        super().nextValidId(orderId)
        self._ready.set()

    def wait_until_ready(self, timeout: float = 2.0) -> bool:
        return self._ready.wait(timeout)

    def request_contract_details(self, contract: Contract, timeout: float = 5.0) -> OptionContract | None:
        req_id = self._next_id()
        event = self._event(req_id)
        self.reqContractDetails(req_id, contract)
        try:
            if not event.wait(timeout):
                logger.debug(
                    "Contract details timeout for "
                    f"{getattr(contract, 'localSymbol', contract)}"
                )
                return None
            details = self._contract_details.pop(req_id, [])
            if not details:
                return None
            first = details[0]
            contract_obj = getattr(first, "contract", None)
            if contract_obj is None:
                return None
            try:
                return OptionContract.from_ib(contract_obj)
            except Exception:
                logger.debug("Failed to parse contract details", exc_info=True)
                return None
        finally:
            self.clear_request(req_id)

    # ------------------------------------------------------------------
    # IB callbacks
    # ------------------------------------------------------------------
    def tickPrice(self, reqId: int, tickType: int, price: float, attrib: Any) -> None:  # noqa: N802 - IB API
        data = self._data(reqId)
        numeric = _is_finite_number(price)
        if tickType == TickTypeEnum.BID and numeric:
            data["bid"] = float(price)
        elif tickType == TickTypeEnum.ASK and numeric:
            data["ask"] = float(price)
        elif tickType == TickTypeEnum.LAST and numeric:
            data["last"] = float(price)
        elif tickType == TickTypeEnum.CLOSE and numeric:
            data.setdefault("last", float(price))
        if numeric and not self._is_snapshot(reqId):
            self._finalize_request(reqId)

    def tickSnapshotEnd(self, reqId: int) -> None:  # noqa: N802 - IB API
        self._finalize_request(reqId)

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
        lastGreeksUpdateTime: float | None = None,
    ) -> None:  # noqa: N802 - IB API
        data = self._data(reqId)
        updated = False
        if _store_numeric(data, "delta", delta):
            updated = True
        if _store_numeric(data, "gamma", gamma):
            updated = True
        if _store_numeric(data, "vega", vega):
            updated = True
        if _store_numeric(data, "theta", theta):
            updated = True
        if _store_numeric(data, "iv", impliedVol):
            updated = True
        if updated and not self._is_snapshot(reqId):
            self._finalize_request(reqId)

    def contractDetails(self, reqId: int, details: ContractDetails) -> None:  # noqa: N802 - IB API
        self._contract_details.setdefault(reqId, []).append(details)

    def contractDetailsEnd(self, reqId: int) -> None:  # noqa: N802 - IB API
        self._event(reqId).set()

    def error(self, reqId: int, errorTime: int, errorCode: int, errorString: str, advancedOrderRejectJson: str = "") -> None:  # noqa: N802 - IB API
        super().error(reqId, errorTime, errorCode, errorString, advancedOrderRejectJson)
        if reqId > 0:
            self._finalize_request(reqId)


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
            else cfg_value("MKT_GENERIC_TICKS", _GENERIC_TICKS)
        )
        if isinstance(cfg_ticks, str):
            cfg_ticks = cfg_ticks.strip()
        self._generic_ticks = cfg_ticks or ""
        if use_snapshot is None:
            use_snapshot = bool(cfg_value("IB_USE_SNAPSHOT_DATA", True))
        self._use_snapshot = bool(use_snapshot)
        self._max_quote_retries = max(int(cfg_value("IB_MAX_QUOTE_RETRIES", 3)), 0)
        self._quote_retry_delay = max(float(cfg_value("IB_QUOTE_RETRY_DELAY", 0.75)), 0.0)

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
        trigger: str | None = None,
        log_delta: bool = True,
    ) -> SnapshotResult:
        if not proposal.legs:
            return SnapshotResult(proposal, [], True, [])

        trigger_label = trigger or "manual"
        timeout = timeout or float(cfg_value("MARKET_DATA_TIMEOUT", 15))
        port = int(cfg_value("IB_PORT", 7497))
        if bool(cfg_value("IB_PAPER_MODE", True)):
            port = int(cfg_value("IB_PORT", 7497))
        else:
            port = int(cfg_value("IB_LIVE_PORT", 7496))
        client_id = int(cfg_value("IB_MARKETDATA_CLIENT_ID", 901))
        host = str(cfg_value("IB_HOST", "127.0.0.1"))

        app = self._app_factory()
        logger.info("📡 Ophalen IB quotes voor voorstel trigger=%s", trigger_label)
        connect_ib(
            client_id=client_id,
            host=host,
            port=port,
            timeout=int(timeout),
            app=app,
        )

        if hasattr(app, "wait_until_ready"):
            app.wait_until_ready(timeout=1.0)

        try:
            missing: list[str] = []
            delta_entries: list[dict[str, Any]] = []
            before_metrics = _capture_metric_snapshot(proposal)
            generic_ticks = self._generic_ticks or ""
            use_snapshot = self._should_use_snapshot()
            if self._use_snapshot and not use_snapshot:
                logger.debug(
                    "Snapshot market data not supported with generic ticks "
                    f"{generic_ticks}; using streaming data instead"
                )
            for leg in proposal.legs:
                try:
                    contract = self._build_contract(
                        leg,
                        log=False,
                        warn_missing=False,
                    )
                    contract = self._maybe_enrich_contract(app, leg, contract, timeout)
                except Exception as exc:
                    logger.warning(f"⚠️ Contract kon niet worden opgebouwd: {exc}")
                    logger.warning(
                        f"IB leg payload bij fout: {pformat(_loggable_leg_payload(leg))}"
                    )
                    missing.append(str(leg.get("strike")))
                    leg["missing_edge"] = True
                    continue
                attempts = 0
                quote_received = False
                retry_delay = self._quote_retry_delay
                max_retries = self._max_quote_retries
                self._log_contract(contract, leg)
                while attempts <= max_retries:
                    attempts += 1
                    req_id = app._next_id()
                    app.register_request(req_id, snapshot=use_snapshot)
                    event = app._event(req_id)
                    logger.debug(
                        "reqMktData "
                        f"req_id={req_id} "
                        f"symbol={getattr(contract, 'symbol', '-')} "
                        f"secType={getattr(contract, 'secType', '-')} "
                        f"expiry={getattr(contract, 'lastTradeDateOrContractMonth', '-')} "
                        f"strike={getattr(contract, 'strike', '-')} "
                        f"right={getattr(contract, 'right', '-')} "
                        f"exchange={getattr(contract, 'exchange', '-')} "
                        f"snapshot={use_snapshot} "
                        f"attempt={attempts}"
                    )
                    app.reqMktData(req_id, contract, generic_ticks, use_snapshot, False, [])
                    try:
                        if not event.wait(timeout):
                            logger.warning(
                                "⏱ Timeout bij ophalen quote voor "
                                f"strike {leg.get('strike')} (poging {attempts})"
                            )
                        else:
                            snapshot = app._responses.get(req_id, {})
                            self._apply_snapshot(
                                leg,
                                snapshot,
                                delta_log=delta_entries if log_delta else None,
                                trigger=trigger_label,
                            )
                            bid_ok = _is_finite_number(snapshot.get("bid"))
                            ask_ok = _is_finite_number(snapshot.get("ask"))
                            if bid_ok and ask_ok:
                                quote_received = True
                                break
                            logger.debug(
                                "Ontbrekende bid/ask na poging "
                                f"{attempts} voor strike {leg.get('strike')} "
                                f"(bid={snapshot.get('bid')}, ask={snapshot.get('ask')})"
                            )
                    finally:
                        try:
                            app.cancelMktData(req_id)
                        except Exception:
                            pass
                        app.clear_request(req_id)

                    if quote_received:
                        break
                    if attempts <= max_retries and retry_delay:
                        time.sleep(retry_delay)

                if not quote_received:
                    missing.append(str(leg.get("strike")))
                    leg["missing_edge"] = True

            score, reasons = scoring.calculate_score(
                proposal.strategy,
                proposal,
                spot=spot_price,
                criteria=criteria,
                atr=proposal.atr,
            )
            accepted = score is not None
            after_metrics = _capture_metric_snapshot(proposal)
            metrics_delta = _compute_metric_delta(before_metrics, after_metrics)
            refreshed_at = datetime.utcnow().isoformat()
            result = SnapshotResult(
                proposal=proposal,
                reasons=reasons,
                accepted=accepted,
                missing_quotes=missing,
                delta_log=list(delta_entries) if log_delta else [],
                trigger=trigger_label,
                metrics_delta=metrics_delta if metrics_delta else None,
                refreshed_at=refreshed_at,
            )
            if log_delta and delta_entries:
                logger.info(
                    "[refresh-summary] trigger=%s legs=%d delta_count=%d accepted=%s",
                    trigger_label,
                    len(proposal.legs),
                    len(delta_entries),
                    accepted,
                )
            result.governance = _governance_payload(proposal, result, trigger_label)
            return result
        finally:
            try:
                app.disconnect()
            except Exception:
                logger.debug("Kon IB verbinding niet netjes sluiten", exc_info=True)

    # ------------------------------------------------------------------
    def _build_contract(
        self,
        leg: Mapping[str, Any],
        *,
        log: bool = True,
        warn_missing: bool = True,
    ) -> Contract:
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
            exchange=str(leg.get("exchange") or cfg_value("OPTIONS_EXCHANGE", "SMART")),
            currency=str(leg.get("currency") or "USD"),
            multiplier=str(leg.get("multiplier") or "100"),
            trading_class=leg.get("tradingClass") or leg.get("trading_class"),
            primary_exchange=leg.get("primaryExchange") or leg.get("primary_exchange"),
            con_id=leg.get("conId") or leg.get("con_id"),
        )
        contract = info.to_ib(
            log=log,
            warn_on_missing_trading_class=warn_missing,
        )
        return contract

    def _maybe_enrich_contract(
        self,
        app: QuoteSnapshotApp,
        leg: Mapping[str, Any],
        contract: Contract,
        timeout: float,
    ) -> Contract:
        if not isinstance(leg, dict):
            return contract
        trading_class = leg.get("tradingClass") or leg.get("trading_class")
        primary_exchange = leg.get("primaryExchange") or leg.get("primary_exchange")
        con_id = leg.get("conId") or leg.get("con_id")
        if trading_class and primary_exchange and con_id:
            return contract
        if not hasattr(app, "request_contract_details"):
            return contract
        details_timeout = max(1.0, min(float(timeout), 5.0))
        try:
            enriched = app.request_contract_details(contract, timeout=details_timeout)
        except Exception:
            logger.debug("Contract details request failed", exc_info=True)
            return contract
        if not enriched:
            return contract

        updated = False
        if enriched.trading_class and not trading_class:
            leg["tradingClass"] = enriched.trading_class
            leg.setdefault("trading_class", enriched.trading_class)
            updated = True
        if enriched.primary_exchange and not primary_exchange:
            leg["primaryExchange"] = enriched.primary_exchange
            leg.setdefault("primary_exchange", enriched.primary_exchange)
            updated = True
        if enriched.con_id and not con_id:
            leg["conId"] = enriched.con_id
            leg.setdefault("con_id", enriched.con_id)
            updated = True
        if not updated:
            return contract
        try:
            return self._build_contract(leg, log=False, warn_missing=False)
        except Exception:
            logger.debug("Failed to rebuild contract with enriched data", exc_info=True)
            return contract

    def _log_contract(self, contract: Contract, leg: Mapping[str, Any]) -> None:
        symbol = _normalize_symbol(leg)
        trading_class = leg.get("tradingClass") or leg.get("trading_class")
        if not trading_class:
            trading_class = getattr(contract, "tradingClass", "") or symbol
            logger.warning(
                "⚠️ tradingClass ontbreekt voor "
                f"{symbol} - fallback naar {trading_class}"
            )
        primary_exchange = (
            getattr(contract, "primaryExchange", None)
            or leg.get("primaryExchange")
            or leg.get("primary_exchange")
            or getattr(contract, "exchange", None)
        )
        parts = {
            "symbol": getattr(contract, "symbol", None),
            "secType": getattr(contract, "secType", None),
            "exchange": getattr(contract, "exchange", None),
            "primaryExchange": primary_exchange,
            "currency": getattr(contract, "currency", None),
            "expiry": getattr(contract, "lastTradeDateOrContractMonth", None),
            "strike": getattr(contract, "strike", None),
            "right": getattr(contract, "right", None),
            "multiplier": getattr(contract, "multiplier", None),
            "tradingClass": trading_class,
        }
        formatted = " ".join(
            f"{key}={value}" for key, value in parts.items() if value not in (None, "")
        )
        logger.debug(f"IB contract built: {formatted}")

    def _apply_snapshot(
        self,
        leg: Mapping[str, Any],
        data: Mapping[str, Any],
        *,
        delta_log: list[dict[str, Any]] | None = None,
        trigger: str | None = None,
    ) -> None:
        if not isinstance(leg, dict):
            raise TypeError("Leg moet mutable mapping zijn")

        previous_mid = leg.get("mid")
        previous_source = (
            str(leg.get("mid_source") or leg.get("mid_fallback") or leg.get("mid_reason") or "")
            or None
        )
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
            rounded_mid = round(mid, 4)
            leg["mid"] = rounded_mid
            leg.pop("missing_edge", None)
            leg["mid_source"] = "true"
            leg["mid_reason"] = "ib_snapshot"
            leg.pop("mid_fallback", None)
            leg.pop("mid_from_parity", None)
            if trigger:
                leg["mid_refresh_trigger"] = trigger
            timestamp = datetime.utcnow().isoformat()
            leg["mid_refresh_timestamp"] = timestamp
            previous_mid_val = None
            try:
                previous_mid_val = float(previous_mid) if previous_mid is not None else None
            except (TypeError, ValueError):
                previous_mid_val = None
            if previous_mid_val is not None:
                leg["mid_previous"] = previous_mid_val
                leg["mid_delta"] = round(rounded_mid - previous_mid_val, 4)
            else:
                leg.pop("mid_previous", None)
                leg.pop("mid_delta", None)

            if delta_log is not None:
                entry = {
                    "symbol": leg.get("symbol") or leg.get("underlying") or leg.get("root"),
                    "expiry": leg.get("expiry"),
                    "strike": leg.get("strike"),
                    "before": previous_mid_val,
                    "after": rounded_mid,
                    "delta": None
                    if previous_mid_val is None
                    else round(rounded_mid - previous_mid_val, 4),
                    "source_before": previous_source,
                    "source_after": "true",
                    "trigger": trigger,
                    "timestamp": timestamp,
                }
                delta_log.append(entry)
                try:
                    strike_label = leg.get("strike")
                    symbol = leg.get("symbol") or leg.get("underlying") or "?"
                    logger.info(
                        "[refresh-delta] %s %s mid %s → %s (Δ=%s) trigger=%s",
                        symbol,
                        strike_label,
                        previous_mid_val,
                        rounded_mid,
                        entry["delta"],
                        trigger or "manual",
                    )
                except Exception:  # pragma: no cover - defensive logging
                    logger.debug("Failed to log refresh delta", exc_info=True)
        else:
            leg["missing_edge"] = True
            leg.pop("mid_refresh_timestamp", None)
            leg.pop("mid_refresh_trigger", None)
            leg.pop("mid_previous", None)
            leg.pop("mid_delta", None)

        delta = leg.get("delta")
        if isinstance(delta, (int, float)):
            right = get_leg_right(leg)
            if right == "put":
                leg["delta"] = -abs(float(delta))
            elif right == "call":
                leg["delta"] = abs(float(delta))

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
    trigger: str | None = None,
    log_delta: bool = True,
    service: IBMarketDataService | None = None,
) -> SnapshotResult:
    """Refresh proposal quotes via IB and recompute metrics."""

    svc = service or IBMarketDataService()
    baseline_metrics = _capture_metric_snapshot(proposal)
    result = svc.refresh(
        proposal,
        criteria=criteria,
        spot_price=spot_price,
        interest_rate=interest_rate,
        timeout=timeout,
        trigger=trigger,
        log_delta=log_delta,
    )
    result.trigger = result.trigger or trigger or "manual"
    if not result.metrics_delta:
        updated_metrics = _capture_metric_snapshot(result.proposal)
        metrics_delta = _compute_metric_delta(baseline_metrics, updated_metrics)
        if metrics_delta:
            result.metrics_delta = metrics_delta
    if not result.governance:
        result.governance = _governance_payload(result.proposal, result, result.trigger)

    metrics_delta = result.metrics_delta or {}
    if metrics_delta:
        changed = {
            key: details
            for key, details in metrics_delta.items()
            if details.get("delta") not in {0, 0.0, None}
        }
    else:
        changed = {}
    if changed:
        logger.info(
            "[refresh-metrics] trigger=%s accepted=%s changes=%s",
            result.trigger,
            result.accepted,
            changed,
        )
    if result.accepted and result.governance and not result.governance.get("needs_refresh"):
        result.proposal.needs_refresh = False
    return result


__all__ = [
    "SnapshotResult",
    "IBMarketDataService",
    "QuoteSnapshotApp",
    "fetch_quote_snapshot",
]

