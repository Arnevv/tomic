"""Helper functions for retrieving volatility metrics."""

from __future__ import annotations

import asyncio
from typing import Dict, Optional

import aiohttp

from tomic.webdata.utils import download_html, download_html_async, parse_patterns
from tomic.analysis.iv_patterns import IV_PATTERNS, EXTRA_PATTERNS
from tomic.logutils import logger


YAHOO_VIX_URL = "https://query1.finance.yahoo.com/v7/finance/quote?symbols=%5EVIX"


async def _fetch_vix_from_yahoo() -> Optional[float]:
    """Return the headline VIX value from Yahoo Finance."""

    timeout = aiohttp.ClientTimeout(total=5)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(YAHOO_VIX_URL, headers={"User-Agent": "Mozilla/5.0"}) as response:
                response.raise_for_status()
                payload = await response.json()
    except Exception as exc:  # pragma: no cover - network failures
        logger.error(f"Failed to fetch VIX quote: {exc}")
        return None

    try:
        results = payload["quoteResponse"]["result"]
        if not results:
            raise ValueError("empty result set")
        value = results[0].get("regularMarketPrice")
        if value is None:
            raise ValueError("missing regularMarketPrice")
        return float(value)
    except (KeyError, ValueError, TypeError, IndexError) as exc:
        logger.error(f"Failed to parse VIX payload: {exc}")
        return None


async def fetch_volatility_metrics_async(symbol: str) -> Dict[str, float]:
    """Asynchronously fetch volatility metrics from the web."""
    html = await download_html_async(symbol)
    iv_data = parse_patterns(IV_PATTERNS, html)
    extra_data = parse_patterns(EXTRA_PATTERNS, html)
    vix_value = extra_data.get("vix")
    if not vix_value:
        vix_fallback = await _fetch_vix_from_yahoo()
        if vix_fallback is not None:
            extra_data["vix"] = vix_fallback
    for key in ("iv_rank", "iv_percentile"):
        if iv_data.get(key) is not None:
            iv_data[key] /= 100
    return {**iv_data, **extra_data}


def fetch_volatility_metrics(symbol: str) -> Dict[str, float]:
    """Return key volatility metrics for ``symbol``.

    Network errors are logged and result in an empty ``dict``.
    """
    try:
        return asyncio.run(fetch_volatility_metrics_async(symbol))
    except Exception as exc:  # pragma: no cover - network failures
        logger.error(f"Failed to fetch volatility metrics for {symbol}: {exc}")
        return {}


__all__ = [
    "download_html",
    "parse_patterns",
    "fetch_volatility_metrics",
    "fetch_volatility_metrics_async",
]
