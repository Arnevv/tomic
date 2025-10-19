"""Legacy helpers for IV rank scraping.

The project no longer scrapes third-party websites for implied volatility data.
These helpers remain only to provide a clear runtime error when the module is
invoked.
"""

from __future__ import annotations

import sys
from typing import Dict, Optional

from tomic.logutils import logger
from tomic.logutils import setup_logging


async def fetch_iv_metrics_async(symbol: str = "SPY") -> Dict[str, Optional[float]]:
    """Async helper kept for backwards compatibility.

    The scraper-based implementation has been removed, so an empty mapping is
    returned. Callers should migrate away from this helper.
    """

    logger.warning(
        "IV metrics scraping has been removed; no data will be returned for %s",
        symbol,
    )
    return {}


def fetch_iv_metrics(symbol: str = "SPY") -> Dict[str, Optional[float]]:
    """Return IV metrics for ``symbol``.

    The legacy scraper is no longer available and an empty mapping is returned
    instead.
    """

    import asyncio

    return asyncio.run(fetch_iv_metrics_async(symbol))


def fetch_iv_rank(symbol: str = "SPY") -> float:
    """Raise a clear error indicating that IV rank scraping is unsupported."""

    raise RuntimeError("IV rank scraping has been removed from tomic")


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
        if metrics:
            logger.info(f"IV metrics for {symbol}: {metrics}")
        else:
            logger.warning("Geen IV-data beschikbaar voor %s", symbol)
        logger.success("✅ IV-scraper aangeroepen (zonder data)")
    except Exception as exc:
        logger.error(f"Error fetching IV metrics: {exc}")


if __name__ == "__main__":
    main()
