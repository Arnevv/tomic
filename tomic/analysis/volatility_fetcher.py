"""Helper functions for retrieving volatility metrics."""

from __future__ import annotations

import asyncio
import re
from typing import Dict, Optional

import aiohttp

from tomic.webdata.utils import download_html, download_html_async, parse_patterns
from tomic.analysis.iv_patterns import IV_PATTERNS, EXTRA_PATTERNS
from tomic.logutils import logger


GOOGLE_VIX_HTML_URL = "https://www.google.com/finance/quote/VIX:INDEXCBOE"
_GOOGLE_VIX_PATTERNS = [
    r"data-last-price=\"([0-9]+(?:[\.,][0-9]+)?)\"",
    r"YMlKec[^>]*>\s*([0-9]+(?:[\.,][0-9]+)?)<",
    r"\"price\"\s*:\s*\{[^}]*\"raw\"\s*:\s*([0-9]+(?:[\.,][0-9]+)?)",
]

YAHOO_VIX_HTML_URL = "https://finance.yahoo.com/quote/%5EVIX/"
_YAHOO_VIX_PATTERNS = [
    r"\"regularMarketPrice\"\s*:\s*\{\s*\"raw\"\s*:\s*([0-9]+(?:[\.,][0-9]+)?)",
    r"data-symbol=\"\^?VIX\"[^>]*data-field=\"regularMarketPrice\"[^>]*value=\"([0-9]+(?:[\.,][0-9]+)?)\"",
    r"data-field=\"regularMarketPrice\"[^>]*data-symbol=\"\^?VIX\"[^>]*value=\"([0-9]+(?:[\.,][0-9]+)?)\"",
    r"data-field=\"regularMarketPrice\"[^>]*data-symbol=\"\^?VIX\"[^>]*>([0-9]+(?:[\.,][0-9]+)?)<",
]


def _to_float(value: str) -> Optional[float]:
    """Convert a captured numeric string into a float."""

    cleaned = value.strip().replace("\xa0", "")
    if "," in cleaned and "." not in cleaned:
        cleaned = cleaned.replace(",", ".")
    else:
        cleaned = cleaned.replace(",", "")
    try:
        return float(cleaned)
    except ValueError:  # pragma: no cover - defensive, shouldn't happen
        logger.warning(f"Failed to coerce numeric value from '{value}'")
        return None


def _parse_vix_from_google(html: str) -> Optional[float]:
    """Extract the VIX value from Google Finance HTML."""

    for pattern in _GOOGLE_VIX_PATTERNS:
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if match:
            value = _to_float(match.group(1))
            if value is not None:
                return value
    return None


def _parse_vix_from_yahoo(html: str) -> Optional[float]:
    """Extract the VIX value from Yahoo Finance HTML."""

    for pattern in _YAHOO_VIX_PATTERNS:
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if match:
            value = _to_float(match.group(1))
            if value is not None:
                return value
    return None


async def _fetch_vix_from_yahoo() -> Optional[float]:
    """Return the headline VIX value from Yahoo Finance."""

    timeout = aiohttp.ClientTimeout(total=5)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                YAHOO_VIX_HTML_URL, headers={"User-Agent": "Mozilla/5.0"}
            ) as response:
                response.raise_for_status()
                html = await response.text()
    except Exception as exc:  # pragma: no cover - network failures
        logger.error(f"Failed to fetch VIX quote: {exc}")
        return None

    value = _parse_vix_from_yahoo(html)
    if value is None:
        logger.error("Failed to parse VIX payload from Yahoo HTML")
    return value


async def _fetch_vix_from_google() -> Optional[float]:
    """Return the headline VIX value from Google Finance."""

    timeout = aiohttp.ClientTimeout(total=5)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                GOOGLE_VIX_HTML_URL, headers={"User-Agent": "Mozilla/5.0"}
            ) as response:
                response.raise_for_status()
                html = await response.text()
    except Exception as exc:  # pragma: no cover - network failures
        logger.error(f"Failed to fetch VIX quote from Google: {exc}")
        return None

    value = _parse_vix_from_google(html)
    if value is None:
        logger.error("Failed to parse VIX payload from Google HTML")
    return value


async def fetch_volatility_metrics_async(symbol: str) -> Dict[str, float]:
    """Asynchronously fetch volatility metrics from the web."""
    html = await download_html_async(symbol)
    iv_data = parse_patterns(IV_PATTERNS, html)
    extra_data = parse_patterns(EXTRA_PATTERNS, html)
    vix_value = await _fetch_vix_from_google()
    if vix_value is None:
        vix_value = await _fetch_vix_from_yahoo()
    extra_data["vix"] = vix_value
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
