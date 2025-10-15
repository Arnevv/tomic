"""Helpers for web scraping tasks."""

from __future__ import annotations

import re
import asyncio
import aiohttp
import urllib.request
from typing import Dict, List, Optional

from tomic.logutils import logger
from tomic.config import get as cfg_get


async def download_html_async(
    symbol: str,
    *,
    max_retries: int | None = None,
    timeout: int | None = None,
) -> str:
    """Asynchronously return raw HTML for the given symbol.

    Parameters
    ----------
    symbol:
        Ticker symbol to fetch.
    max_retries:
        Number of retry attempts when the request fails. Defaults to the
        ``DOWNLOAD_RETRIES`` config value.
    timeout:
        Socket timeout in seconds for each request. Defaults to the
        ``DOWNLOAD_TIMEOUT`` config value.
    """

    if max_retries is None:
        max_retries = int(cfg_get("DOWNLOAD_RETRIES", 2))
    if timeout is None:
        timeout = int(cfg_get("DOWNLOAD_TIMEOUT", 10))

    url = f"https://www.barchart.com/etfs-funds/quotes/{symbol}/volatility-charts"

    for attempt in range(1, max_retries + 1):
        logger.debug(
            f"Requesting volatility page for {symbol} at {url} "
            f"(attempt {attempt}/{max_retries})"
        )
        try:
            timeout_obj = aiohttp.ClientTimeout(total=timeout)
            async with aiohttp.ClientSession(timeout=timeout_obj) as session:
                async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}) as response:
                    response.raise_for_status()
                    html = await response.text()
            logger.debug(f"Downloaded {len(html)} characters from {url}")
            return html
        except Exception as exc:  # pragma: no cover - network errors
            logger.error(f"Download failed: {exc}")
            if attempt >= max_retries:
                raise
            await asyncio.sleep(1)


def download_html(
    symbol: str,
    *,
    max_retries: int | None = None,
    timeout: int | None = None,
) -> str:
    """Synchronous wrapper for :func:`download_html_async`."""
    return asyncio.run(download_html_async(symbol, max_retries=max_retries, timeout=timeout))


def parse_patterns(patterns: Dict[str, List[str]], html: str) -> Dict[str, Optional[float]]:
    """Return numeric values extracted using ``patterns``."""
    results: Dict[str, Optional[float]] = {}
    for key, pats in patterns.items():
        logger.debug(
            f"Searching HTML for '{key}' using {len(pats)} pattern(s)"
        )
        for pat in pats:
            logger.debug(f"Trying pattern '{pat}' for {key}")
            match = re.search(pat, html, re.IGNORECASE | re.DOTALL)
            if match:
                try:
                    results[key] = float(match.group(1))
                    logger.debug(
                        f"Matched pattern '{pat}' for {key} -> {results[key]}"
                    )
                    break
                except ValueError:
                    logger.warning(
                        f"Failed to parse {key} from '{match.group(1)}'"
                    )
                    break
        if key not in results:
            logger.error(f"{key} not found on page")
            results[key] = None
    return results


__all__ = ["download_html", "download_html_async", "parse_patterns"]
