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
from tomic.models import MarketMetrics
from tomic.config import get as cfg_get


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
    records = [
        data
        for req_id, data in app.market_data.items()
        if req_id not in app.invalid_contracts and req_id not in spot_ids
    ]
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
                parity = (call_mid - put_mid) - (
                    app.spot_price - strike * math.exp(-r * t)
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
                ]
            )
    logger.info(f"✅ [stap 10] Optieketen opgeslagen in: {chain_file}")
    total = len(getattr(app, "market_data", {})) - len(spot_ids)
    logger.info(
        f"Contracts verwerkt: {len(records)} geldig, {total - len(records)} ongeldig"
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
        for req_id, rec in app.market_data.items():
            if req_id in spot_ids:
                continue
            if req_id in getattr(app, "invalid_contracts", set()):
                continue
            if (
                rec.get("bid") is None
                and rec.get("ask") is None
                and rec.get("close") is None
            ):
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
                ]
            )
    logger.info(f"✅ [stap 10] CSV opgeslagen als: {path}")
    total = len(getattr(app, "market_data", {})) - len(spot_ids)
    valid = sum(
        1
        for req_id, rec in app.market_data.items()
        if req_id not in getattr(app, "invalid_contracts", set())
        and req_id not in spot_ids
        and not (
            rec.get("bid") is None
            and rec.get("ask") is None
            and rec.get("close") is None
        )
    )
    logger.info(f"Contracts verwerkt: {valid} geldig, {total - valid} ongeldig")


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
    if not await_market_data(app, symbol, timeout=120):
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
            timeout=cfg_get("MARKET_DATA_TIMEOUT", 120),
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
    if not await_market_data(app, symbol, timeout=120):
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
    "export_market_data_async",
    "export_option_chain_async",
    "start_app_async",
    "await_market_data_async",
    "fetch_market_metrics_async",
]
