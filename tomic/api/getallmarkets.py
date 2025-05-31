import threading
import time
import csv
import os
from datetime import datetime
import pandas as pd
from tomic.logging import logger, setup_logging
from tomic.api.combined_app import CombinedApp
from tomic.api.market_utils import fetch_market_metrics
from tomic.config import get as cfg_get


def run(symbol: str, output_dir: str | None = None):
    symbol = symbol.upper()
    if not symbol:
        logger.error("❌ Geen geldig symbool ingevoerd.")
        return

    try:
        metrics = fetch_market_metrics(symbol)
    except Exception as exc:
        logger.error("❌ Marktkenmerken ophalen mislukt: %s", exc)
        return

    app = CombinedApp(symbol)
    host = cfg_get("IB_HOST", "127.0.0.1")
    port = int(cfg_get("IB_PORT", 7497))
    app.connect(host, port, clientId=200)
    thread = threading.Thread(target=app.run, daemon=True)
    thread.start()

    if not app.spot_price_event.wait(timeout=10):
        logger.error("❌ Spotprijs ophalen mislukt.")
        app.disconnect()
        return

    if not app.contract_details_event.wait(timeout=10):
        logger.error("❌ Geen contractdetails ontvangen.")
        app.disconnect()
        return

    if not app.conId:
        logger.error("❌ Geen conId ontvangen.")
        app.disconnect()
        return

    app.reqSecDefOptParams(1201, symbol, "", "STK", app.conId)
    if not app.option_params_event.wait(timeout=10):
        logger.error("❌ Geen expiries ontvangen.")
        app.disconnect()
        return

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

    if output_dir is None:
        today_str = datetime.now().strftime("%Y%m%d")
        export_dir = os.path.join(cfg_get("EXPORT_DIR", "exports"), today_str)
    else:
        export_dir = output_dir
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
                    (
                        round(data.get("delta"), 3)
                        if data.get("delta") is not None
                        else None
                    ),
                    (
                        round(data.get("gamma"), 3)
                        if data.get("gamma") is not None
                        else None
                    ),
                    (
                        round(data.get("vega"), 3)
                        if data.get("vega") is not None
                        else None
                    ),
                    (
                        round(data.get("theta"), 3)
                        if data.get("theta") is not None
                        else None
                    ),
                ]
            )

    logger.info("✅ Optieketen opgeslagen in: %s", chain_file)

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
        writer.writerow(headers_metrics)
        writer.writerow(values_metrics)

    logger.info("✅ CSV opgeslagen als: %s", metrics_file)

    app.disconnect()
    time.sleep(1)
    df_metrics = pd.DataFrame([values_metrics], columns=headers_metrics)
    return df_metrics


def export_combined_csv(data_per_market, output_dir):
    """Combine individual market DataFrames and export to a single CSV."""
    combined_df = pd.concat(data_per_market, ignore_index=True)
    output_path = os.path.join(output_dir, "Overzicht_Marktkenmerken.csv")
    combined_df.to_csv(output_path, index=False)
    logger.info("%d markten verwerkt. CSV geëxporteerd.", len(data_per_market))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Exporteer data voor meerdere markten")
    parser.add_argument(
        "symbols",
        nargs="*",
        help="Symbolen om te verwerken",
    )
    parser.add_argument(
        "--output-dir",
        help="Map voor exports (standaard wordt automatisch bepaald)",
    )
    args = parser.parse_args()

    setup_logging()
    logger.info("🚀 Start export")

    default_symbols = [
        "AAPL",
        "ASML",
        "CRM",
        "DIA",
        "EWG",
        "EWJ",
        "EWZ",
        "FEZ",
        "FXI",
        "GLD",
        "INDA",
        "NVDA",
        "QQQ",
        "RUT",
        "SPY",
        "TSLA",
        "VIX",
        "XLE",
        "XLF",
        "XLV",
    ]
    symbols = args.symbols or default_symbols

    if args.output_dir is None:
        today_str = datetime.now().strftime("%Y%m%d")
        export_dir = os.path.join(cfg_get("EXPORT_DIR", "exports"), today_str)
    else:
        export_dir = args.output_dir

    data_frames = []
    for sym in symbols:
        logger.info("🔄 Ophalen voor %s...", sym)
        df = run(sym, export_dir)
        if df is not None:
            data_frames.append(df)
        time.sleep(2)

    unique_markets = {df["Symbol"].iloc[0] for df in data_frames}
    if len(unique_markets) > 1:
        export_combined_csv(data_frames, export_dir)

    logger.success("✅ Export afgerond voor %d markten", len(unique_markets))
