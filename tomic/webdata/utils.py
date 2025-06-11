"""Helpers for web scraping tasks."""

from __future__ import annotations

import re
import time
import urllib.request
from typing import Dict, List, Optional

from tomic.logutils import logger
from tomic.config import get as cfg_get


def download_html(
    symbol: str,
    *,
    max_retries: int | None = None,
    timeout: int | None = None,
) -> str:
    """Return raw HTML for the given symbol from Barchart.

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
        logger.debug(f"Requesting URL: {url} (attempt {attempt})")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                html = response.read().decode("utf-8", errors="ignore")
            logger.debug(f"Downloaded {len(html)} characters")
            return html
        except Exception as exc:  # pragma: no cover - network errors
            logger.error(f"Download failed: {exc}")
            if attempt >= max_retries:
                raise
            time.sleep(1)


def parse_patterns(patterns: Dict[str, List[str]], html: str) -> Dict[str, Optional[float]]:
    """Return numeric values extracted using ``patterns``."""
    results: Dict[str, Optional[float]] = {}
    for key, pats in patterns.items():
        for pat in pats:
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


__all__ = ["download_html", "parse_patterns"]
