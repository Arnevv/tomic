def start_app(app: MarketClient) -> None:
    """Connect to TWS/IB Gateway and start ``app`` in a background thread."""
    host = cfg_get("IB_HOST", "127.0.0.1")
    port = int(cfg_get("IB_PORT", 7497))
    client_id = int(cfg_get("IB_CLIENT_ID", 100))
    app.connect(host, port, client_id)
    thread = threading.Thread(target=app.run, daemon=True)
    thread.start()
    start = time.time()
    while app.next_valid_id is None and time.time() - start < 5:
        time.sleep(0.1)


def await_market_data(app: MarketClient, symbol: str, timeout: int = 10) -> bool:
    """Wait until market data has been populated or timeout occurs."""
    start = time.time()
    while time.time() - start < timeout:
        if app.market_data or app.spot_price is not None:
            return True
        time.sleep(0.1)
    logger.error(f"❌ Timeout terwijl gewacht werd op data voor {symbol}")
    return False


def fetch_market_metrics(symbol: str) -> dict[str, Any] | None:
    """Return key volatility metrics scraped from Barchart + optional spot via IB."""
    data = fetch_volatility_metrics(symbol.upper())
    metrics: Dict[str, Any] = {
        "spot_price": data.get("spot_price"),
        "hv30": data.get("hv30"),
        "atr14": None,
        "vix": None,
        "skew": data.get("skew"),
        "term_m1_m2": None,
        "term_m1_m3": None,
        "iv_rank": data.get("iv_rank"),
        "implied_volatility": data.get("implied_volatility"),
        "iv_percentile": data.get("iv_percentile"),
    }

    # Probeer live spot price van IB
    app = MarketClient(symbol)
    start_app(app)
    if hasattr(app, "start_requests"):
        app.start_requests()
    if await_market_data(app, symbol):
        metrics["spot_price"] = app.spot_price or metrics["spot_price"]
    app.disconnect()

    logger.debug(f"Fetched metrics for {symbol}: {metrics}")
    return metrics
