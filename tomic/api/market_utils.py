"""Utility functions for market data retrieval."""

import threading
import time
import math
import statistics
import itertools
import socket

from tomic.config import get as cfg_get

from ibapi.contract import Contract

from tomic.logging import logger
from tomic.analysis.get_iv_rank import fetch_iv_metrics

# Global client ID counter for unique connections
_client_id_counter = itertools.count(start=1)

INDEX_SYMBOLS = {"RUT", "VIX"}

# --- Connection helpers -----------------------------------------------------


def ib_connection_available(
    host: str | None = None,
    port: int | None = None,
    *,
    timeout: float = 2.0,
) -> bool:
    """Return ``True`` if a socket connection to IB can be established."""

    host = host or cfg_get("IB_HOST", "127.0.0.1")
    port = int(port or cfg_get("IB_PORT", 7497))
    try:
        with socket.create_connection((host, port), timeout):
            return True
    except OSError:
        return False


def ib_api_available(
    host: str | None = None,
    port: int | None = None,
    *,
    timeout: float = 2.0,
) -> bool:
    """Return ``True`` if a basic IB API connection succeeds."""

    from tomic.core.ib import BaseApp

    class _PingApp(BaseApp):
        def __init__(self) -> None:
            super().__init__()
            self.ready_event = threading.Event()

        def nextValidId(self, orderId: int) -> None:  # noqa: N802 - IB API callback
            self.ready_event.set()

    app = _PingApp()
    try:
        start_app(app, host=host, port=port, client_id=1)
        return app.ready_event.wait(timeout=timeout)
    except Exception:
        return False
    finally:
        try:
            app.disconnect()
        except Exception:
            pass


# --- App helpers ------------------------------------------------------------


def start_app(
    app, host: str | None = None, port: int | None = None, client_id: int | None = None
) -> threading.Thread:
    """Connect and start the IB API client.

    Parameters are optional and fall back to ``config.yaml`` defaults. When no
    ``client_id`` is provided, a unique identifier is generated for each
    connection.
    """

    if client_id is None:
        client_id = next(_client_id_counter)

    if hasattr(app, "start"):
        thread = app.start(host=host, port=port, client_id=client_id)
    else:
        host = host or cfg_get("IB_HOST", "127.0.0.1")
        port = int(port or cfg_get("IB_PORT", 7497))
        app.connect(host, port, clientId=client_id)
        thread = threading.Thread(target=app.run, daemon=True)
        thread.start()

    # Explicitly initiate the API to avoid hanging connections on some systems
    if hasattr(app, "startApi"):
        time.sleep(0.1)
        try:
            app.startApi()
        except Exception:
            pass

    return thread


def await_market_data(app, symbol: str) -> bool:
    """Wait until option market data is received."""
    if not app.spot_price_event.wait(timeout=10):
        logger.error("❌ Spotprijs ophalen mislukt.")
        return False
    if not app.contract_details_event.wait(timeout=10):
        logger.error("❌ Geen contractdetails ontvangen.")
        return False
    if not getattr(app, "conId", None):
        logger.error("❌ Geen conId ontvangen.")
        return False

    sec_type = "IND" if symbol.upper() in INDEX_SYMBOLS else "STK"
    app.reqSecDefOptParams(1201, symbol, "", sec_type, app.conId)
    if not app.option_params_event.wait(timeout=10):
        logger.error("❌ Geen expiries ontvangen.")
        return False
    logger.info("⏳ Wachten op marketdata (10 seconden)...")
    time.sleep(10)
    total = len([k for k in app.market_data if k not in app.invalid_contracts])
    incomplete = app.count_incomplete()
    waited = 10
    while incomplete > 0 and waited < 60:
        logger.info(
            f"⏳ {incomplete} van {total} opties niet compleet na {waited} seconden. Wachten..."
        )
        time.sleep(5)
        waited += 5
        incomplete = app.count_incomplete()
    if incomplete > 0:
        logger.warning(
            f"⚠️ {incomplete} opties blijven incompleet na {waited} seconden. Berekeningen gaan verder met beschikbare data."
        )
    else:
        logger.info(f"✅ Alle opties volledig na {waited} seconden.")
    return True


def count_incomplete(records: list[dict]) -> int:
    """Return how many option records miss market, Greek or volume data."""

    required_fields = {
        "bid",
        "ask",
        "iv",
        "delta",
        "gamma",
        "vega",
        "theta",
        "volume",
    }

    return sum(
        1 for rec in records if any(rec.get(field) is None for field in required_fields)
    )


def create_underlying(symbol: str) -> Contract:
    """Return a stock or index ``Contract`` for the given symbol."""

    c = Contract()
    c.symbol = symbol

    if symbol.upper() in INDEX_SYMBOLS:
        c.secType = "IND"
        if symbol.upper() == "RUT":
            c.exchange = "RUSSELL"
        else:
            c.exchange = "CBOE"
    else:
        c.secType = "STK"
        c.exchange = "SMART"
        c.primaryExchange = "ARCA"

    c.currency = "USD"
    return c


def create_option_contract(
    symbol: str,
    expiry: str,
    strike: float,
    right: str,
    trading_class: str | None = None,
) -> Contract:
    """Return an option Contract for the given parameters."""
    c = Contract()
    c.symbol = symbol
    c.secType = "OPT"
    c.exchange = "SMART"
    c.primaryExchange = "SMART"
    c.currency = "USD"
    c.lastTradeDateOrContractMonth = expiry
    c.strike = strike
    c.right = right[0].upper() if right else right
    c.multiplier = "100"
    c.tradingClass = trading_class or symbol
    return c


def calculate_hv30(historical_data: list) -> float | None:
    """Return the 30-day historical volatility percentage."""
    closes = [bar.close for bar in historical_data if hasattr(bar, "close")]
    if len(closes) < 2:
        return None
    log_returns = [math.log(closes[i + 1] / closes[i]) for i in range(len(closes) - 1)]
    std_dev = statistics.stdev(log_returns)
    return round(std_dev * math.sqrt(252) * 100, 2)


def calculate_atr14(historical_data: list) -> float | None:
    """Return the 14-day average true range."""
    trs = []
    for i in range(1, len(historical_data)):
        high = historical_data[i].high
        low = historical_data[i].low
        prev_close = historical_data[i - 1].close
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    if len(trs) < 14:
        return None
    atr14 = statistics.mean(trs[-14:])
    return round(atr14, 2)


def fetch_market_metrics(symbol: str) -> dict | None:
    """Return key market metrics for the given symbol using the IB API."""
    from .combined_app import CombinedApp

    symbol = symbol.upper()
    app = CombinedApp(symbol)
    host = cfg_get("IB_HOST", "127.0.0.1")
    port = int(cfg_get("IB_PORT", 7497))
    # Use a unique client ID for every connection to prevent IB error 326
    start_app(app, host=host, port=port)

    if not app.spot_price_event.wait(timeout=10):
        app.disconnect()
        raise RuntimeError("Spot price retrieval failed")

    if not app.contract_details_event.wait(timeout=10) or not app.conId:
        app.disconnect()
        raise RuntimeError("Contract details not received")

    sec_type = "IND" if symbol.upper() in INDEX_SYMBOLS else "STK"
    app.reqSecDefOptParams(1201, symbol, "", sec_type, app.conId)
    if not app.option_params_event.wait(timeout=10):
        app.disconnect()
        raise RuntimeError("Option parameters not received")

    app.historical_event.clear()
    app.get_historical_data()
    if not app.historical_event.wait(timeout=15):
        app.disconnect()
        raise RuntimeError("Historical data retrieval failed")

    hv30 = app.calculate_hv30()
    atr14 = app.calculate_atr14()

    try:
        iv_data = fetch_iv_metrics(symbol)
        iv_rank = iv_data.get("iv_rank")
        implied_volatility = iv_data.get("implied_volatility")
        iv_percentile = iv_data.get("iv_percentile")
    except Exception:
        iv_rank = None
        implied_volatility = None
        iv_percentile = None

    if not app.vix_event.wait(timeout=10):
        app.disconnect()
        raise RuntimeError("VIX retrieval failed")

    time.sleep(10)
    waited = 10
    while app.count_incomplete() > 0 and waited < 60:
        time.sleep(5)
        waited += 5

    valid_options = [
        d
        for k, d in app.market_data.items()
        if k not in app.invalid_contracts
        and d.get("delta") is not None
        and d.get("iv") is not None
    ]

    if not app.expiries:
        logger.error("❌ Geen expiries ontvangen voor %s", symbol)
        app.disconnect()
        return None

    expiry = app.expiries[0]
    calls = [d for d in valid_options if d["right"] == "C" and d["expiry"] == expiry]
    puts = [d for d in valid_options if d["right"] == "P" and d["expiry"] == expiry]

    def interpolate_iv_at_delta(options, target_delta):
        if not options:
            return None, None
        sorted_opts = sorted(options, key=lambda x: x["delta"])
        for i in range(len(sorted_opts) - 1):
            d1, d2 = sorted_opts[i]["delta"], sorted_opts[i + 1]["delta"]
            if d1 is None or d2 is None:
                continue
            if (d1 <= target_delta <= d2) or (d2 <= target_delta <= d1):
                iv1, iv2 = sorted_opts[i]["iv"], sorted_opts[i + 1]["iv"]
                k1, k2 = sorted_opts[i]["strike"], sorted_opts[i + 1]["strike"]
                if iv1 is None or iv2 is None:
                    continue
                weight = 0 if d1 == d2 else (target_delta - d1) / (d2 - d1)
                iv = iv1 + weight * (iv2 - iv1)
                strike = (
                    k1 + weight * (k2 - k1)
                    if k1 is not None and k2 is not None
                    else None
                )
                return iv, strike
        nearest = min(sorted_opts, key=lambda x: abs(x["delta"] - target_delta))
        return nearest["iv"], nearest.get("strike")

    atm_call_ivs = []
    for exp in app.expiries:
        exp_calls = [
            d for d in valid_options if d["right"] == "C" and d["expiry"] == exp
        ]
        iv, _ = interpolate_iv_at_delta(exp_calls, 0.50)
        atm_call_ivs.append(iv)

    call_iv, _ = interpolate_iv_at_delta(calls, 0.25)
    put_iv, _ = interpolate_iv_at_delta(puts, -0.25)

    skew = (
        round(call_iv - put_iv, 2)
        if call_iv is not None and put_iv is not None
        else None
    )

    m1 = atm_call_ivs[0] if len(atm_call_ivs) > 0 else None
    m2 = atm_call_ivs[1] if len(atm_call_ivs) > 1 else None
    m3 = atm_call_ivs[2] if len(atm_call_ivs) > 2 else None

    term_m1_m2 = None if m1 is None or m2 is None else round(m2 - m1, 4)
    term_m1_m3 = None if m1 is None or m3 is None else round(m3 - m1, 4)

    metrics = {
        "spot_price": app.spot_price,
        "hv30": hv30,
        "atr14": atr14,
        "vix": app.vix_price,
        "skew": skew,
        "term_m1_m2": term_m1_m2,
        "term_m1_m3": term_m1_m3,
        "iv_rank": iv_rank,
        "implied_volatility": implied_volatility,
        "iv_percentile": iv_percentile,
    }

    app.disconnect()
    time.sleep(1)
    return metrics


__all__ = [
    "ib_connection_available",
    "ib_api_available",
    "create_underlying",
    "create_option_contract",
    "calculate_hv30",
    "calculate_atr14",
    "start_app",
    "await_market_data",
    "count_incomplete",
    "fetch_market_metrics",
]
