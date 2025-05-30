"""Utility functions for market data retrieval."""

import threading
import time

from tomic.analysis.get_iv_rank import fetch_iv_metrics
from tomic.api.combined_app import CombinedApp


def fetch_market_metrics(symbol: str) -> dict:
    """Return key market metrics for the given symbol using the IB API."""
    symbol = symbol.upper()
    app = CombinedApp(symbol)
    app.connect("127.0.0.1", 7497, clientId=201)
    thread = threading.Thread(target=app.run, daemon=True)
    thread.start()

    if not app.spot_price_event.wait(timeout=10):
        app.disconnect()
        raise RuntimeError("Spot price retrieval failed")

    if not app.contract_details_event.wait(timeout=10) or not app.conId:
        app.disconnect()
        raise RuntimeError("Contract details not received")

    app.reqSecDefOptParams(1201, symbol, "", "STK", app.conId)
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
        if k not in app.invalid_contracts and d.get("delta") is not None and d.get("iv") is not None
    ]

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
                strike = k1 + weight * (k2 - k1) if k1 is not None and k2 is not None else None
                return iv, strike
        nearest = min(sorted_opts, key=lambda x: abs(x["delta"] - target_delta))
        return nearest["iv"], nearest.get("strike")

    atm_call_ivs = []
    for exp in app.expiries:
        exp_calls = [d for d in valid_options if d["right"] == "C" and d["expiry"] == exp]
        iv, _ = interpolate_iv_at_delta(exp_calls, 0.50)
        atm_call_ivs.append(iv)

    call_iv, _ = interpolate_iv_at_delta(calls, 0.25)
    put_iv, _ = interpolate_iv_at_delta(puts, -0.25)

    skew = round(call_iv - put_iv, 2) if call_iv is not None and put_iv is not None else None

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
