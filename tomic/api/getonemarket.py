import threading
import time
import csv
import os
import math
import statistics
from datetime import datetime, timezone
import logging
from tomic.analysis.get_iv_rank import fetch_iv_metrics
from tomic.logging import setup_logging
from tomic.api.combined_app import CombinedApp



def run():
    setup_logging()
    symbol = input(
        "📈 Voer het symbool in waarvoor je data wilt ophalen (bijv. SPY): "
    ).strip().upper()
    if not symbol:
        logging.error("❌ Geen geldig symbool ingevoerd.")
        return

    app = CombinedApp(symbol)
    app.connect("127.0.0.1", 7497, clientId=200)
    thread = threading.Thread(target=app.run, daemon=True)
    thread.start()

    if not app.spot_price_event.wait(timeout=10):
        logging.error("❌ Spotprijs ophalen mislukt.")
        app.disconnect()
        return

    if not app.contract_details_event.wait(timeout=10):
        logging.error("❌ Geen contractdetails ontvangen.")
        app.disconnect()
        return

    if not app.conId:
        logging.error("❌ Geen conId ontvangen.")
        app.disconnect()
        return

    app.reqSecDefOptParams(1201, symbol, "", "STK", app.conId)
    if not app.option_params_event.wait(timeout=10):
        logging.error("❌ Geen expiries ontvangen.")
        app.disconnect()
        return

    app.historical_event.clear()
    app.get_historical_data()
    if not app.historical_event.wait(timeout=15):
        logging.error("❌ Historische data ophalen mislukt.")
        app.disconnect()
        return

    hv30 = app.calculate_hv30()
    atr14 = app.calculate_atr14()

    try:
        iv_data = fetch_iv_metrics(symbol)
        iv_rank = iv_data.get("iv_rank")
        implied_volatility = iv_data.get("implied_volatility")
        iv_percentile = iv_data.get("iv_percentile")
    except Exception as exc:
        logging.error("⚠️ IV metrics ophalen mislukt: %s", exc)
        iv_rank = None
        implied_volatility = None
        iv_percentile = None

    if not app.vix_event.wait(timeout=10):
        logging.error("❌ VIX ophalen mislukt.")
        app.disconnect()
        return

    logging.info("⏳ Wachten op marketdata (10 seconden)...")
    time.sleep(10)

    total_options = len([k for k in app.market_data if k not in app.invalid_contracts])
    incomplete = app.count_incomplete()
    waited = 10
    max_wait = 60
    interval = 5
    while incomplete > 0 and waited < max_wait:
        logging.info(
            "⏳ %s van %s opties niet compleet na %s seconden. Wachten...",
            incomplete,
            total_options,
            waited,
        )
        time.sleep(interval)
        waited += interval
        incomplete = app.count_incomplete()

    if incomplete > 0:
        logging.warning(
            "⚠️ %s opties blijven incompleet na %s seconden. Berekeningen gaan verder met beschikbare data.",
            incomplete,
            waited,
        )
    else:
        logging.info("✅ Alle opties volledig na %s seconden.", waited)

    today_str = datetime.now().strftime("%Y%m%d")
    export_dir = os.path.join("exports", today_str)
    os.makedirs(export_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    chain_file = os.path.join(export_dir, f"option_chain_{symbol}_{timestamp}.csv")
    headers_chain = [
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
    ]
    with open(chain_file, "w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(headers_chain)
        for data in app.market_data.values():
            writer.writerow(
                [
                    data.get("expiry"),
                    data.get("right"),
                    data.get("strike"),
                    data.get("bid"),
                    data.get("ask"),
                    round(data.get("iv"), 3) if data.get("iv") is not None else None,
                    round(data.get("delta"), 3) if data.get("delta") is not None else None,
                    round(data.get("gamma"), 3) if data.get("gamma") is not None else None,
                    round(data.get("vega"), 3) if data.get("vega") is not None else None,
                    round(data.get("theta"), 3) if data.get("theta") is not None else None,
                ]
            )

    logging.info("✅ Optieketen opgeslagen in: %s", chain_file)

    valid_options = [
        d
        for k, d in app.market_data.items()
        if k not in app.invalid_contracts and d.get("delta") is not None and d.get("iv") is not None
    ]

    expiry = app.expiries[0]
    logging.info("📆 Skew berekend op expiry: %s", expiry)

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
        iv, strike = interpolate_iv_at_delta(exp_calls, 0.50)
        atm_call_ivs.append(iv)
        if iv is not None:
            logging.info("📈 ATM IV %s: %.4f (strike ~ %s)", exp, iv, strike)
        else:
            logging.warning("⚠️ Geen ATM IV beschikbaar voor %s", exp)

    call_iv, _ = interpolate_iv_at_delta(calls, 0.25)
    put_iv, _ = interpolate_iv_at_delta(puts, -0.25)

    if call_iv is not None and put_iv is not None:
        skew = round((call_iv - put_iv) * 100, 2)
        logging.info(
            "📐 Skew (25d CALL - 25d PUT): %.4f - %.4f = %.2f",
            call_iv,
            put_iv,
            skew,
        )
    else:
        logging.warning("⚠️ Onvoldoende data voor skew-berekening.")
        skew = None

    m1 = atm_call_ivs[0] if len(atm_call_ivs) > 0 else None
    m2 = atm_call_ivs[1] if len(atm_call_ivs) > 1 else None
    m3 = atm_call_ivs[2] if len(atm_call_ivs) > 2 else None

    term_m1_m2 = (
        None if m1 is None or m2 is None else round((m2 - m1) * 100, 2)
    )
    term_m1_m3 = (
        None if m1 is None or m3 is None else round((m3 - m1) * 100, 2)
    )

    logging.info("📊 Term m1->m2: %s", term_m1_m2 if term_m1_m2 is not None else "n.v.t.")
    logging.info("📊 Term m1->m3: %s", term_m1_m3 if term_m1_m3 is not None else "n.v.t.")

    metrics_file = os.path.join(export_dir, f"other_data_{symbol}_{timestamp}.csv")
    headers_metrics = [
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
    values_metrics = [
        symbol,
        app.spot_price,
        hv30,
        atr14,
        app.vix_price,
        skew,
        term_m1_m2,
        term_m1_m3,
        iv_rank,
        implied_volatility,
        iv_percentile,
    ]

    with open(metrics_file, "w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(headers_metrics)
        writer.writerow(values_metrics)

    logging.info("✅ CSV opgeslagen als: %s", metrics_file)

    app.disconnect()
    time.sleep(1)


if __name__ == "__main__":
    run()
