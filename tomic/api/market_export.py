"""Shared market data export helpers.

``OptionChainClient`` retrieves only a subset of the option chain. It keeps the
first four expiries and strikes whose rounded value is within ±STRIKE_RANGE
points of the rounded spot price (configured via ``STRIKE_RANGE``). The helpers
in this module work with that same selection.

All export routines disconnect from Interactive Brokers as soon as all market
data has been received. The files are written after the disconnect so the TWS
connection is not kept open longer than necessary.
"""

from __future__ import annotations

import csv
import os
import time
from datetime import datetime
import math

import pandas as pd

from tomic.logutils import logger, log_result
import asyncio
from typing import Any
import threading
from tomic.api.market_client import (
    MarketClient,
    OptionChainClient,
    TermStructureClient,
    fetch_market_metrics,
    start_app,
    await_market_data,
)
from ibapi.contract import Contract
from tomic.models import MarketMetrics, OptionContract
from tomic.config import get as cfg_get
from .historical_iv import fetch_historical_option_data


_HEADERS_CHAIN = [
    "Expiry",
    "Type",
    "Strike",
    "Bid",
    "Ask",
    "Close",
    "IV",
    "Delta",
    "Gamma",
    "Vega",
    "Theta",
    "Volume",
    "OpenInterest",
    "ParityDeviation",
    "Status",
]

_HEADERS_METRICS = [
    "Symbol",
    "SpotPrice",
    "HV_30",
    "ATR_14",
    "VIX",
    "Skew",
    "Term_M1_M2",
    "Term_M1_M3",
    "IV_Rank",
    "Implied_Volatility",
    "IV_Percentile",
    "Avg_Parity_Deviation",
]

_HEADERS_SIMPLE = [
    "Symbol",
    "Expiry",
    "Strike",
    "Type",
    "Bid",
    "Ask",
    "Close",
    "IV",
    "Delta",
    "Gamma",
    "Vega",
    "Theta",
    "Status",
]


@log_result
def _write_option_chain(
    app: MarketClient, symbol: str, export_dir: str, timestamp: str
) -> float | None:
    logger.info("▶️ START stap 10 - Exporteren van data naar CSV")
    chain_file = os.path.join(export_dir, f"option_chain_{symbol}_{timestamp}.csv")
    spot_ids = set(getattr(app, "_spot_req_ids", []))
    single = getattr(app, "_spot_req_id", None)
    if single is not None:
        spot_ids.add(single)
    counts = {"ok": 0, "fallback": 0, "timeout": 0, "invalid": 0}
    records = []
    for req_id, data in app.market_data.items():
        if req_id in spot_ids:
            continue
        status = data.get("status", "ok")
        if req_id in app.invalid_contracts and status == "ok":
            status = "invalid"
            data["status"] = "invalid"
        if status in ("timeout", "invalid"):
            for key in [
                "bid",
                "ask",
                "close",
                "iv",
                "delta",
                "gamma",
                "vega",
                "theta",
                "volume",
                "open_interest",
                "parity_deviation",
            ]:
                data.setdefault(key, None)
        counts[status] = counts.get(status, 0) + 1
        records.append(data)
    if not records:
        logger.warning(f"Geen optie data ontvangen voor {symbol}")
        return None

    def _mid(bid: float | None, ask: float | None) -> float | None:
        """Return midpoint price when bid/ask are valid and positive."""

        if bid is None or ask is None or bid < 0 or ask < 0:
            return None

        return (bid + ask) / 2

    grouped: dict[tuple[str, float], dict[str, dict]] = {}
    parity_values: list[float] = []
    expiries = getattr(app, "expiries", [])
    target_expiry = expiries[0] if expiries else None
    for rec in records:
        if rec.get("status") in ("timeout", "invalid"):
            continue
        key = (rec.get("expiry"), rec.get("strike"))
        pair = grouped.setdefault(key, {})
        if rec.get("right") == "C":
            pair["call"] = rec
        elif rec.get("right") == "P":
            pair["put"] = rec

    today = datetime.now().date()
    r = cfg_get("INTEREST_RATE", 0.05)
    for (expiry, strike), pair in grouped.items():
        call = pair.get("call")
        put = pair.get("put")
        parity = None
        if (
            call
            and put
            and strike is not None
            and app.spot_price is not None
            and call.get("bid") is not None
            and call.get("ask") is not None
            and put.get("bid") is not None
            and put.get("ask") is not None
        ):
            call_mid = _mid(call.get("bid"), call.get("ask"))
            put_mid = _mid(put.get("bid"), put.get("ask"))
            try:
                if call_mid is None or put_mid is None:
                    raise ValueError("invalid mid")
                exp_date = datetime.strptime(str(expiry), "%Y%m%d").date()
                t = max((exp_date - today).days, 0) / 365
                parity = abs(
                    (call_mid - put_mid)
                    - (app.spot_price - strike * math.exp(-r * t))
                )
                parity = round(parity, 4)
            except Exception:
                parity = None
        if parity is not None and expiry == target_expiry:
            parity_values.append(parity)
        if call is not None:
            call["parity_deviation"] = parity
        if put is not None:
            put["parity_deviation"] = parity

    with open(chain_file, "w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(_HEADERS_CHAIN)
        for rec in records:
            writer.writerow(
                [
                    rec.get("expiry"),
                    rec.get("right"),
                    rec.get("strike"),
                    rec.get("bid"),
                    rec.get("ask"),
                    rec.get("close"),
                    round(rec.get("iv"), 3) if rec.get("iv") is not None else None,
                    (
                        round(rec.get("delta"), 3)
                        if rec.get("delta") is not None
                        else None
                    ),
                    (
                        round(rec.get("gamma"), 3)
                        if rec.get("gamma") is not None
                        else None
                    ),
                    (
                        round(rec.get("vega"), 3)
                        if rec.get("vega") is not None
                        else None
                    ),
                    (
                        round(rec.get("theta"), 3)
                        if rec.get("theta") is not None
                        else None
                    ),
                    rec.get("volume"),
                    rec.get("open_interest"),
                    rec.get("parity_deviation"),
                    rec.get("status", "ok"),
                ]
            )
    logger.info(f"✅ [stap 10] Optieketen opgeslagen in: {chain_file}")
    total = len(getattr(app, "market_data", {})) - len(spot_ids)
    logger.info(
        f"Contracts verwerkt: ok={counts['ok']} fallback={counts['fallback']} timeout={counts['timeout']} invalid={counts['invalid']}"
    )
    if parity_values:
        return round(sum(parity_values) / len(parity_values), 4)
    return None


@log_result
def _write_option_chain_simple(
    app: MarketClient, symbol: str, export_dir: str, timestamp: str
) -> None:
    """Write a basic option chain without parity calculations."""

    path = os.path.join(export_dir, f"option_chain_{symbol}_{timestamp}.csv")
    with open(path, "w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(_HEADERS_SIMPLE)
        spot_ids = set(getattr(app, "_spot_req_ids", []))
        single = getattr(app, "_spot_req_id", None)
        if single is not None:
            spot_ids.add(single)
        counts = {"ok": 0, "fallback": 0, "timeout": 0, "invalid": 0}
        for req_id, rec in app.market_data.items():
            if req_id in spot_ids:
                continue
            status = rec.get("status", "ok")
            if req_id in getattr(app, "invalid_contracts", set()) and status == "ok":
                status = "invalid"
                rec["status"] = "invalid"
            if status in ("timeout", "invalid"):
                for key in [
                    "bid",
                    "ask",
                    "close",
                    "iv",
                    "delta",
                    "gamma",
                    "vega",
                    "theta",
                ]:
                    rec.setdefault(key, None)
            counts[status] = counts.get(status, 0) + 1
            if (
                rec.get("bid") is None
                and rec.get("ask") is None
                and rec.get("close") is None
            ) and status == "ok":
                continue
            writer.writerow(
                [
                    symbol,
                    rec.get("expiry"),
                    rec.get("strike"),
                    rec.get("right"),
                    rec.get("bid"),
                    rec.get("ask"),
                    rec.get("close"),
                    rec.get("iv"),
                    rec.get("delta"),
                    rec.get("gamma"),
                    rec.get("vega"),
                    rec.get("theta"),
                    rec.get("status", "ok"),
                ]
            )
    logger.info(f"✅ [stap 10] CSV opgeslagen als: {path}")
    total = len(getattr(app, "market_data", {})) - len(spot_ids)
    logger.info(
        f"Contracts verwerkt: ok={counts['ok']} fallback={counts['fallback']} timeout={counts['timeout']} invalid={counts['invalid']}"
    )


@log_result
def _write_metrics_csv(
    metrics: MarketMetrics,
    symbol: str,
    export_dir: str,
    timestamp: str,
    avg_parity_dev: float | None,
) -> pd.DataFrame:
    logger.info("▶️ START stap 10 - Exporteren van data naar CSV")
    metrics_file = os.path.join(export_dir, f"other_data_{symbol}_{timestamp}.csv")
    values_metrics = [
        symbol,
        metrics.spot_price,
        metrics.hv30,
        metrics.atr14,
        metrics.vix,
        metrics.skew,
        metrics.term_m1_m2,
        metrics.term_m1_m3,
        metrics.iv_rank,
        metrics.implied_volatility,
        metrics.iv_percentile,
        avg_parity_dev,
    ]
    with open(metrics_file, "w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(_HEADERS_METRICS)
        writer.writerow(values_metrics)
    logger.info(f"✅ [stap 10] CSV opgeslagen als: {metrics_file}")
    return pd.DataFrame([values_metrics], columns=_HEADERS_METRICS)


@log_result
def export_market_metrics(
    symbol: str, output_dir: str | None = None, *, client_id: int | None = None
) -> pd.DataFrame | None:
    """Export only market metrics for ``symbol`` to a CSV file."""
    symbol = symbol.strip().upper()
    if not symbol:
        logger.error("❌ Geen geldig symbool ingevoerd.")
        return None
    app = TermStructureClient(symbol)
    start_app(app, client_id=client_id)
    try:
        raw_metrics = fetch_market_metrics(
            symbol,
            app=app,
            timeout=cfg_get("MARKET_DATA_TIMEOUT", 120),
        )
    except Exception as exc:  # pragma: no cover - network failures
        logger.error(f"❌ Marktkenmerken ophalen mislukt: {exc}")
        app.disconnect()
        return None
    if raw_metrics is None:
        logger.error(f"❌ Geen expiries gevonden voor {symbol}")
        app.disconnect()
        return None
    metrics = MarketMetrics.from_dict(raw_metrics)
    if output_dir is None:
        today_str = datetime.now().strftime("%Y%m%d")
        export_dir = os.path.join(cfg_get("EXPORT_DIR", "exports"), today_str)
    else:
        export_dir = output_dir
    os.makedirs(export_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    df_metrics = _write_metrics_csv(metrics, symbol, export_dir, timestamp, None)
    app.disconnect()
    logger.success(f"✅ Marktdata verwerkt voor {symbol}")
    return df_metrics


@log_result
def export_option_chain(
    symbol: str, output_dir: str | None = None, *, simple: bool = False, client_id: int | None = None
) -> float | None:
    """Export only the option chain for ``symbol`` to a CSV file."""
    logger.info("▶️ START stap 1 - Invoer van symbool")
    symbol = symbol.strip().upper()
    if not symbol or not symbol.replace(".", "").isalnum():
        logger.error("❌ FAIL stap 1: ongeldig symbool.")
        return None
    logger.info(f"✅ [stap 1] {symbol} ontvangen, ga nu aan de slag!")
    logger.info("▶️ START stap 2 - Initialiseren client + verbinden met IB")
    app = OptionChainClient(symbol)
    start_app(app, client_id=client_id)
    if not await_market_data(app, symbol, timeout=30):
        logger.warning("⚠️ Marktdata onvolledig, ga verder met beschikbare data")
        app.disconnect()
        time.sleep(1)
        if output_dir is None:
            today_str = datetime.now().strftime("%Y%m%d")
            export_dir = os.path.join(cfg_get("EXPORT_DIR", "exports"), today_str)
        else:
            export_dir = output_dir
        os.makedirs(export_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        if simple:
            _write_option_chain_simple(app, symbol, export_dir, timestamp)
            logger.success(f"✅ Optieketen verwerkt voor {symbol}")
            return None
        avg_parity = _write_option_chain(app, symbol, export_dir, timestamp)
        logger.success(f"✅ Optieketen verwerkt voor {symbol}")
        return avg_parity

    app.disconnect()
    app.disconnect()
    time.sleep(1)
    if output_dir is None:
        today_str = datetime.now().strftime("%Y%m%d")
        export_dir = os.path.join(cfg_get("EXPORT_DIR", "exports"), today_str)
    else:
        export_dir = output_dir
    os.makedirs(export_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    if simple:
        _write_option_chain_simple(app, symbol, export_dir, timestamp)
        avg_parity = None
    else:
        avg_parity = _write_option_chain(app, symbol, export_dir, timestamp)
    logger.success(f"✅ Optieketen verwerkt voor {symbol}")
    return avg_parity


class BulkOptionChainClient(OptionChainClient):
    """Lightweight client using bulk contract qualification."""

    def __init__(self, symbol: str) -> None:
        super().__init__(symbol)
        self.error_count = 0

    def error(
        self, reqId, errorTime, errorCode, errorString, advancedOrderRejectJson=""
    ):  # noqa: D401
        if errorCode in {200, 300}:
            self.error_count += 1
        super().error(reqId, errorTime, errorCode, errorString, advancedOrderRejectJson)

    def contractDetails(self, reqId: int, details):  # noqa: N802
        con = details.contract
        if con.secType == "STK" and self.con_id is None:
            super().contractDetails(reqId, details)
            return
        if reqId in self._pending_details:
            if not self._step8_logged:
                logger.info("▶️ START stap 8 - Callback: contractDetails() voor opties")
                self._step8_logged = True
            self.option_info[reqId] = details
            with self.data_lock:
                self.market_data.setdefault(reqId, {})["conId"] = con.conId
            info = self._pending_details.get(reqId)
            if info is not None:
                info.con_id = con.conId
                self.con_ids[(info.expiry, info.strike, info.right)] = con.conId
                min_tick = getattr(details, "minTick", None)
                if min_tick and info.expiry not in self._expiry_min_tick:
                    self._expiry_min_tick[info.expiry] = float(min_tick)
                    lookup = {s: round(round(s / min_tick) * min_tick, 10) for s in self.strikes}
                    self._exp_strike_lookup[info.expiry] = lookup
            if reqId in self._pending_details:
                self._pending_details.pop(reqId, None)
                self._detail_semaphore.release()
            self.contract_received.set()

    def _request_option_data(self) -> None:
        if not self.expiries or not self.strikes or self.trading_class is None:
            return
        self.all_data_event.clear()
        with self.data_lock:
            self._completed_requests.clear()
        self._use_snapshot = not self.market_open
        self.use_hist_iv = (
            not self.market_open and cfg_get("USE_HISTORICAL_IV_WHEN_CLOSED", False)
        )

        contract_map: dict[int, Contract] = {}
        for expiry in self.expiries:
            for strike in self.strikes:
                actual = self._exp_strike_lookup.get(expiry, {}).get(
                    strike, self._strike_lookup.get(strike, strike)
                )
                for right in ("C", "P"):
                    info = OptionContract(
                        self.symbol,
                        expiry,
                        actual,
                        right,
                        exchange=self.options_exchange,
                        trading_class=self.trading_class,
                        primary_exchange=self.options_primary_exchange,
                        multiplier=self.multiplier,
                        con_id=self.con_ids.get((expiry, strike, right)),
                    )
                    c = info.to_ib()
                    req_id = self._next_id()
                    with self.data_lock:
                        self.market_data[req_id] = {
                            "expiry": expiry,
                            "strike": strike,
                            "right": right,
                            "event": threading.Event(),
                        }
                        self._pending_details[req_id] = info
                    contract_map[req_id] = c
                    self._detail_semaphore.acquire()
                    self.reqContractDetails(req_id, c)
                    time.sleep(0.01)

        timeout = cfg_get("CONTRACT_DETAILS_TIMEOUT", 2) * (
            int(cfg_get("CONTRACT_DETAILS_RETRIES", 0)) + 1
        )
        start = time.time()
        while time.time() - start < timeout and self._pending_details:
            self.contract_received.wait(timeout - (time.time() - start))
            self.contract_received.clear()

        for rid, info in list(self._pending_details.items()):
            logger.warning(
                f"Geen contractdetails gevonden voor {info.symbol} {info.expiry} {info.strike} {info.right}"
            )
            with self.data_lock:
                self.invalid_contracts.add(rid)
            self._detail_semaphore.release()
            self._pending_details.pop(rid, None)

        logger.info(
            f"✅ BULK validatie: {len(self.option_info)} van {len(contract_map)} contracts goedgekeurd"
        )

        if self.use_hist_iv:
            contracts = {
                rid: self.option_info[rid].contract for rid in self.option_info
            }
            bulk_results = fetch_historical_option_data(contracts, app=self)
            self._merge_historical_data(contracts, bulk_results)
            for rid in contracts:
                self._mark_complete(rid)
            return

        for rid, details in self.option_info.items():
            con = details.contract
            if self.data_type_success is not None:
                data_type = self.data_type_success
            else:
                data_type = 1 if self.market_open else 2
            use_snapshot = self._use_snapshot
            include_greeks = (
                not cfg_get("INCLUDE_GREEKS_ONLY_IF_MARKET_OPEN", False)
                or self.market_open
            )
            if use_snapshot:
                generic = ""
            else:
                tick_cfg = cfg_get("MKT_GENERIC_TICKS", "")
                if tick_cfg:
                    generic = tick_cfg
                else:
                    ticks = ["100", "101"]
                    if include_greeks:
                        ticks.append("106")
                    generic = ",".join(ticks)
            self.reqMktData(rid, con, generic, use_snapshot, False, [])
            self._schedule_invalid_timer(rid)


@log_result
def export_option_chain_bulk(
    symbol: str,
    output_dir: str | None = None,
    *,
    simple: bool = False,
    client_id: int | None = None,
) -> float | None:
    """Export option chain using the BulkQualifyFlow."""

    logger.info("▶️ START stap 1 - Invoer van symbool")
    symbol = symbol.strip().upper()
    if not symbol or not symbol.replace(".", "").isalnum():
        logger.error("❌ FAIL stap 1: ongeldig symbool.")
        return None
    logger.info(f"✅ [stap 1] {symbol} ontvangen, ga nu aan de slag!")
    logger.info("▶️ START stap 2 - Initialiseren client + verbinden met IB")
    app = BulkOptionChainClient(symbol)
    start_app(app, client_id=client_id)
    if not await_market_data(app, symbol, timeout=480):
        logger.warning("⚠️ Marktdata onvolledig, ga verder met beschikbare data")
        app.disconnect()
        time.sleep(1)
        if output_dir is None:
            today_str = datetime.now().strftime("%Y%m%d")
            export_dir = os.path.join(cfg_get("EXPORT_DIR", "exports"), today_str)
        else:
            export_dir = output_dir
        os.makedirs(export_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        ts = f"BULK_{ts}"
        if simple:
            _write_option_chain_simple(app, symbol, export_dir, ts)
            logger.success(f"✅ Optieketen verwerkt voor {symbol}")
            return None
        avg_parity = _write_option_chain(app, symbol, export_dir, ts)
        logger.success(f"✅ Optieketen verwerkt voor {symbol}")
        return avg_parity

    app.disconnect()
    time.sleep(1)
    if output_dir is None:
        today_str = datetime.now().strftime("%Y%m%d")
        export_dir = os.path.join(cfg_get("EXPORT_DIR", "exports"), today_str)
    else:
        export_dir = output_dir
    os.makedirs(export_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    ts = f"BULK_{ts}"
    if simple:
        _write_option_chain_simple(app, symbol, export_dir, ts)
        avg_parity = None
    else:
        avg_parity = _write_option_chain(app, symbol, export_dir, ts)
    logger.success(f"✅ Optieketen verwerkt voor {symbol}")
    logger.info(
        f"🆕 BULK valid contracts: {len(app.market_data) - len(app.invalid_contracts)} / {len(app.market_data)}"
    )
    if app.error_count:
        logger.info(f"🆕 BULK vermeden errors 200/300: {app.error_count}")
    return avg_parity



@log_result
def export_market_data(
    symbol: str,
    output_dir: str | None = None,
    *,
    client_id: int | None = None,
    app: OptionChainClient | None = None,
) -> pd.DataFrame | None:
    """Export option chain and market metrics for ``symbol`` to CSV files."""
    logger.info("▶️ START stap 1 - Invoer van symbool")
    symbol = symbol.strip().upper()
    if not symbol or not symbol.replace(".", "").isalnum():
        logger.error("❌ FAIL stap 1: ongeldig symbool.")
        return None
    logger.info(f"✅ [stap 1] {symbol} ontvangen, ga nu aan de slag!")
    logger.info("▶️ START stap 2 - Initialiseren client + verbinden met IB")
    owns_app = False
    if app is None:
        app = OptionChainClient(symbol)
        start_app(app, client_id=client_id)
        owns_app = True
    try:
        raw_metrics = fetch_market_metrics(
            symbol,
            app=app,
            timeout=cfg_get("MARKET_DATA_TIMEOUT", 30),
        )
    except Exception as exc:  # pragma: no cover - network failures
        logger.error(f"❌ Marktkenmerken ophalen mislukt: {exc}")
        if owns_app:
            app.disconnect()
        return None
    if raw_metrics is None:
        logger.error(f"❌ Geen expiries gevonden voor {symbol}")
        if owns_app:
            app.disconnect()
        return None
    metrics = MarketMetrics.from_dict(raw_metrics)
    if not await_market_data(app, symbol, timeout=30):
        logger.warning("⚠️ Marktdata onvolledig, exporteer beschikbare data")
        if owns_app:
            app.disconnect()
            time.sleep(1)
        if output_dir is None:
            today_str = datetime.now().strftime("%Y%m%d")
            export_dir = os.path.join(cfg_get("EXPORT_DIR", "exports"), today_str)
        else:
            export_dir = output_dir
        os.makedirs(export_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        avg_parity = _write_option_chain(app, symbol, export_dir, timestamp)
        df_metrics = _write_metrics_csv(
            metrics, symbol, export_dir, timestamp, avg_parity
        )
        logger.success(f"✅ Marktdata verwerkt voor {symbol}")
        return df_metrics
    if owns_app:
        app.disconnect()
        time.sleep(1)
    if output_dir is None:
        today_str = datetime.now().strftime("%Y%m%d")
        export_dir = os.path.join(cfg_get("EXPORT_DIR", "exports"), today_str)
    else:
        export_dir = output_dir
    os.makedirs(export_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    avg_parity = _write_option_chain(app, symbol, export_dir, timestamp)
    df_metrics = _write_metrics_csv(
        metrics, symbol, export_dir, timestamp, avg_parity
    )
    logger.success(f"✅ Marktdata verwerkt voor {symbol}")
    return df_metrics


async def start_app_async(app: MarketClient, *, client_id: int | None = None) -> None:
    """Async wrapper for :func:`start_app`."""
    await asyncio.to_thread(start_app, app, client_id=client_id)


async def await_market_data_async(
    app: MarketClient,
    symbol: str,
    timeout: int = 30,
    *,
    lock: threading.Lock | None = None,
) -> bool:
    """Async wrapper for :func:`await_market_data`.

    If ``lock`` is not provided the client's internal lock is used.
    """

    def runner() -> bool:
        used_lock = lock or app._lock
        with used_lock:
            return await_market_data(app, symbol, timeout)

    return await asyncio.to_thread(runner)


async def fetch_market_metrics_async(
    symbol: str,
    app: MarketClient | None = None,
    *,
    lock: threading.Lock | None = None,
) -> dict[str, Any] | None:
    """Async wrapper for :func:`fetch_market_metrics`.

    If ``lock`` is not provided and ``app`` is supplied, the client's internal
    lock is used.
    """

    def runner() -> dict[str, Any] | None:
        used_lock = lock or (app._lock if app is not None else None)
        if used_lock is None:
            return fetch_market_metrics(
                symbol,
                app=app,
                timeout=cfg_get("MARKET_DATA_TIMEOUT", 120),
            )
        with used_lock:
            return fetch_market_metrics(
                symbol,
                app=app,
                timeout=cfg_get("MARKET_DATA_TIMEOUT", 120),
            )

    return await asyncio.to_thread(runner)


async def export_option_chain_async(
    symbol: str, output_dir: str | None = None, *, simple: bool = False, client_id: int | None = None
) -> float | None:
    """Async version of :func:`export_option_chain`."""

    logger.info("▶️ START stap 1 - Invoer van symbool")
    symbol = symbol.strip().upper()
    if not symbol or not symbol.replace(".", "").isalnum():
        logger.error("❌ FAIL stap 1: ongeldig symbool.")
        return None
    logger.info(f"✅ [stap 1] {symbol} ontvangen, ga nu aan de slag!")
    logger.info("▶️ START stap 2 - Initialiseren client + verbinden met IB")
    app = OptionChainClient(symbol)
    await start_app_async(app, client_id=client_id)
    ok = await await_market_data_async(app, symbol, timeout=60)
    if not ok:
        logger.warning("⚠️ Marktdata onvolledig, ga verder met beschikbare data")
        app.disconnect()
        await asyncio.sleep(1)
        if output_dir is None:
            today_str = datetime.now().strftime("%Y%m%d")
            export_dir = os.path.join(cfg_get("EXPORT_DIR", "exports"), today_str)
        else:
            export_dir = output_dir
        os.makedirs(export_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        if simple:
            await asyncio.to_thread(
                _write_option_chain_simple, app, symbol, export_dir, timestamp
            )
            logger.success(f"✅ Optieketen verwerkt voor {symbol}")
            return None
        avg_parity = await asyncio.to_thread(
            _write_option_chain, app, symbol, export_dir, timestamp
        )
        logger.success(f"✅ Optieketen verwerkt voor {symbol}")
        return avg_parity
    app.disconnect()
    await asyncio.sleep(1)
    if output_dir is None:
        today_str = datetime.now().strftime("%Y%m%d")
        export_dir = os.path.join(cfg_get("EXPORT_DIR", "exports"), today_str)
    else:
        export_dir = output_dir
    os.makedirs(export_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    if simple:
        await asyncio.to_thread(
            _write_option_chain_simple, app, symbol, export_dir, timestamp
        )
        avg_parity = None
    else:
        avg_parity = await asyncio.to_thread(
            _write_option_chain, app, symbol, export_dir, timestamp
        )
    logger.success(f"✅ Optieketen verwerkt voor {symbol}")
    return avg_parity


async def export_market_data_async(
    symbol: str,
    output_dir: str | None = None,
    *,
    client_id: int | None = None,
    app: OptionChainClient | None = None,
) -> pd.DataFrame | None:
    """Async version of :func:`export_market_data`."""

    logger.info("▶️ START stap 1 - Invoer van symbool")
    symbol = symbol.strip().upper()
    if not symbol or not symbol.replace(".", "").isalnum():
        logger.error("❌ FAIL stap 1: ongeldig symbool.")
        return None
    logger.info(f"✅ [stap 1] {symbol} ontvangen, ga nu aan de slag!")
    logger.info("▶️ START stap 2 - Initialiseren client + verbinden met IB")
    owns_app = False
    if app is None:
        app = OptionChainClient(symbol)
        await start_app_async(app, client_id=client_id)
        owns_app = True
    lock = threading.Lock()
    try:
        raw_metrics, ok = await asyncio.gather(
            fetch_market_metrics_async(symbol, app=app, lock=lock),
            await_market_data_async(app, symbol, timeout=60, lock=lock),
        )
    except Exception as exc:  # pragma: no cover - network failures
        logger.error(f"❌ Marktkenmerken ophalen mislukt: {exc}")
        if owns_app:
            app.disconnect()
        return None
    if raw_metrics is None:
        logger.error(f"❌ Geen expiries gevonden voor {symbol}")
        if owns_app:
            app.disconnect()
        return None
    metrics = MarketMetrics.from_dict(raw_metrics)
    if not ok:
        logger.warning("⚠️ Marktdata onvolledig, exporteer beschikbare data")
        if owns_app:
            app.disconnect()
            await asyncio.sleep(1)
        if output_dir is None:
            today_str = datetime.now().strftime("%Y%m%d")
            export_dir = os.path.join(cfg_get("EXPORT_DIR", "exports"), today_str)
        else:
            export_dir = output_dir
        os.makedirs(export_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        avg_parity = await asyncio.to_thread(
            _write_option_chain, app, symbol, export_dir, timestamp
        )
        df_metrics = await asyncio.to_thread(
            _write_metrics_csv, metrics, symbol, export_dir, timestamp, avg_parity
        )
        logger.success(f"✅ Marktdata verwerkt voor {symbol}")
        return df_metrics
    if owns_app:
        app.disconnect()
        await asyncio.sleep(1)
    if output_dir is None:
        today_str = datetime.now().strftime("%Y%m%d")
        export_dir = os.path.join(cfg_get("EXPORT_DIR", "exports"), today_str)
    else:
        export_dir = output_dir
    os.makedirs(export_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    avg_parity = await asyncio.to_thread(
        _write_option_chain, app, symbol, export_dir, timestamp
    )
    df_metrics = await asyncio.to_thread(
        _write_metrics_csv, metrics, symbol, export_dir, timestamp, avg_parity
    )
    logger.success(f"✅ Marktdata verwerkt voor {symbol}")
    return df_metrics


__all__ = [
    "export_market_data",
    "export_market_metrics",
    "export_option_chain",
    "export_option_chain_bulk",
    "export_market_data_async",
    "export_option_chain_async",
    "start_app_async",
    "await_market_data_async",
    "fetch_market_metrics_async",
]
