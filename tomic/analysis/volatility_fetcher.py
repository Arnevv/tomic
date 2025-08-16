"""Helper functions for retrieving volatility metrics."""

from __future__ import annotations

import asyncio
from typing import Dict

from tomic.webdata.utils import download_html, download_html_async, parse_patterns
from tomic.analysis.iv_patterns import IV_PATTERNS, EXTRA_PATTERNS
from tomic.logutils import logger


async def fetch_volatility_metrics_async(symbol: str) -> Dict[str, float]:
    """Asynchronously fetch volatility metrics from the web."""
    html = await download_html_async(symbol)
    iv_data = parse_patterns(IV_PATTERNS, html)
    extra_data = parse_patterns(EXTRA_PATTERNS, html)
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
