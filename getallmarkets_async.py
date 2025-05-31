import asyncio
from tomic.api.getallmarkets_async import gather_markets
from tomic.logging import logger, setup_logging


if __name__ == "__main__":
    setup_logging()
    logger.info("🚀 Async market export")
    symbols = [
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
    asyncio.run(gather_markets(symbols))
