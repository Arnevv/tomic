"""Shared market data export helpers."""

from __future__ import annotations

import csv
import os
import threading
import time
from datetime import datetime
import math

import pandas as pd

from tomic.logging import logger
from tomic.api.combined_app import CombinedApp
from tomic.api.market_utils import fetch_market_metrics
from tomic.config import get as cfg_get


_HEADERS_CHAIN = [
    "Expiry",
    "Type",
    "Strike",
    "Bid",
    "Ask",
    "IV",
    "Delta",
    "Gamma",
    "Vega",
    "Theta",
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
]


def _start_app(app: CombinedApp) -> None:
    """Connect and start the IBKR app in a background thread."""
    host = cfg_get("IB_HOST", "127.0.0.1")
    port = int(cfg_get("IB_PORT", 7497))
    app.connect(host, port, clientId=200)
    thread = threading.Thread(target=app.run, daemon=True)
    thread.start()


def _await_market_data(app: CombinedApp, symbol: str) -> bool:
    """Wait for option market data to be fully received."""
    if not app.spot_price_event.wait(timeout=10):
        logger.error("❌ Spotprijs ophalen mislukt.")
        return False
    if not app.contract_details_event.wait(timeout=10):
        logger.error("❌ Geen contractdetails ontvangen.")
        return False
    if not app.conId:
        logger.error("❌ Geen conId ontvangen.")
        return False
    app.reqSecDefOptParams(1201, symbol, "", "STK", app.conId)
    if not app.option_params_event.wait(timeout=10):
        logger.error("❌ Geen expiries ontvangen.")
        return False
    logger.info("⏳ Wachten op marketdata (10 seconden)...")
    time.sleep(10)
    total_options = len([k for k in app.market_data if k not in app.invalid_contracts])
    incomplete = app.count_incomplete()
    waited = 10
    max_wait = 60
    interval = 5
    while incomplete > 0 and waited < max_wait:
        logger.info(
            "⏳ %s van %s opties niet compleet na %s seconden. Wachten...",
            incomplete,
            total_options,
            waited,
        )
        time.sleep(interval)
        waited += interval
        incomplete = app.count_incomplete()
    if incomplete > 0:
        logger.warning(
            "⚠️ %s opties blijven incompleet na %s seconden. Berekeningen gaan verder met beschikbare data.",
            incomplete,
            waited,
        )
    else:
        logger.info("✅ Alle opties volledig na %s seconden.", waited)
    return True


def _write_option_chain(
    app: CombinedApp, symbol: str, export_dir: str, timestamp: str
) -> None:
    chain_file = os.path.join(export_dir, f"option_chain_{symbol}_{timestamp}.csv")
    records = [
        data
        for req_id, data in app.market_data.items()
        if req_id not in app.invalid_contracts
    ]

    def _mid(bid: float | None, ask: float | None) -> float | None:
        if bid is None or ask is None:
            return None
        return (bid + ask) / 2

    grouped: dict[tuple[str, float], dict[str, dict]] = {}
    for rec in records:
        key = (rec.get("expiry"), rec.get("strike"))
        pair = grouped.setdefault(key, {})
        if rec.get("right") == "C":
            pair["call"] = rec
        elif rec.get("right") == "P":
            pair["put"] = rec

    today = datetime.now().date()
    r = 0.05
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
                exp_date = datetime.strptime(str(expiry), "%Y%m%d").date()
                t = max((exp_date - today).days, 0) / 365
                parity = (call_mid - put_mid) - (
                    app.spot_price - strike * math.exp(-r * t)
                )
                parity = round(parity, 4)
            except Exception:
                parity = None
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
                    rec.get("parity_deviation"),
                ]
            )
    logger.info("✅ Optieketen opgeslagen in: %s", chain_file)


def _write_metrics_csv(
    metrics: dict, symbol: str, export_dir: str, timestamp: str
) -> pd.DataFrame:
    metrics_file = os.path.join(export_dir, f"other_data_{symbol}_{timestamp}.csv")
    values_metrics = [
        symbol,
        metrics.get("spot_price"),
        metrics.get("hv30"),
        metrics.get("atr14"),
        metrics.get("vix"),
        metrics.get("skew"),
        metrics.get("term_m1_m2"),
        metrics.get("term_m1_m3"),
        metrics.get("iv_rank"),
        metrics.get("implied_volatility"),
        metrics.get("iv_percentile"),
    ]
    with open(metrics_file, "w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(_HEADERS_METRICS)
        writer.writerow(values_metrics)
    logger.info("✅ CSV opgeslagen als: %s", metrics_file)
    return pd.DataFrame([values_metrics], columns=_HEADERS_METRICS)


def export_market_data(
    symbol: str, output_dir: str | None = None
) -> pd.DataFrame | None:
    """Export option chain and market metrics for ``symbol`` to CSV files."""
    symbol = symbol.strip().upper()
    if not symbol:
        logger.error("❌ Geen geldig symbool ingevoerd.")
        return None
    try:
        metrics = fetch_market_metrics(symbol)
    except Exception as exc:  # pragma: no cover - network failures
        logger.error("❌ Marktkenmerken ophalen mislukt: %s", exc)
        return None
    app = CombinedApp(symbol)
    _start_app(app)
    if not _await_market_data(app, symbol):
        app.disconnect()
        return None
    if output_dir is None:
        today_str = datetime.now().strftime("%Y%m%d")
        export_dir = os.path.join(cfg_get("EXPORT_DIR", "exports"), today_str)
    else:
        export_dir = output_dir
    os.makedirs(export_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    _write_option_chain(app, symbol, export_dir, timestamp)
    df_metrics = _write_metrics_csv(metrics, symbol, export_dir, timestamp)
    app.disconnect()
    time.sleep(1)
    logger.success("✅ Marktdata verwerkt voor %s", symbol)
    return df_metrics


__all__ = ["export_market_data"]
