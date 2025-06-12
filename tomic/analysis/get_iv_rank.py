import sys

from typing import Dict, Optional

from tomic.analysis.iv_patterns import IV_PATTERNS
import asyncio
from tomic.webdata.utils import download_html, download_html_async, parse_patterns
from tomic.logutils import logger
from tomic.logutils import setup_logging


async def fetch_iv_metrics_async(symbol: str = "SPY") -> Dict[str, Optional[float]]:
    """Async helper to fetch IV metrics for the symbol."""
    html = await download_html_async(symbol)
    return parse_patterns(IV_PATTERNS, html)


def fetch_iv_metrics(symbol: str = "SPY") -> Dict[str, Optional[float]]:
    """Return IV Rank, Implied Volatility and IV Percentile for the symbol."""
    return asyncio.run(fetch_iv_metrics_async(symbol))


def fetch_iv_rank(symbol: str = "SPY") -> float:
    """Fetch only the IV Rank for the given symbol."""
    metrics = fetch_iv_metrics(symbol)
    iv_rank = metrics.get("iv_rank")
    if iv_rank is None:
        raise ValueError("IV Rank not found on page")
    return iv_rank


def main(argv=None):
    setup_logging()
    if argv is None:
        argv = sys.argv[1:]

    symbol = (
        argv[0] if argv else input("Ticker (default SPY): ")
    ).strip().upper() or "SPY"
    logger.info(f"🚀 Fetching IV metrics for {symbol}")

    try:
        metrics = fetch_iv_metrics(symbol)
        iv_rank = metrics.get("iv_rank")
        implied_vol = metrics.get("implied_volatility")
        iv_pct = metrics.get("iv_percentile")

        logger.info(f"IV Rank for {symbol}: {iv_rank}")
        logger.info(f"Implied Volatility: {implied_vol}")
        logger.info(f"IV Percentile: {iv_pct}")
        logger.success("✅ Metrics fetched")
    except Exception as exc:
        logger.error(f"Error fetching IV metrics: {exc}")


if __name__ == "__main__":
    main()
