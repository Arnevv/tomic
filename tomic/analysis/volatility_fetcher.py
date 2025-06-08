"""Utilities to download volatility HTML and parse regex patterns."""

from __future__ import annotations

import re
import urllib.request
from typing import Dict, List, Optional

from tomic.logutils import logger


def download_html(symbol: str) -> str:
    """Retrieve the volatility page HTML for ``symbol`` from Barchart."""
    url = f"https://www.barchart.com/etfs-funds/quotes/{symbol}/volatility-charts"
    logger.debug(f"Requesting URL: {url}")

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as response:
        html = response.read().decode("utf-8", errors="ignore")
    logger.debug(f"Downloaded {len(html)} characters")
    return html


def parse_patterns(
    patterns: Dict[str, List[str]], html: str
) -> Dict[str, Optional[float]]:
    """Return a dict with parsed numeric values using ``patterns``."""
    results: Dict[str, Optional[float]] = {}
    for key, pats in patterns.items():
        for pat in pats:
            match = re.search(pat, html, re.IGNORECASE | re.DOTALL)
            if match:
                try:
                    results[key] = float(match.group(1))
                    logger.debug(f"Matched pattern '{pat}' for {key} -> {results[key]}")
                    break
                except ValueError:
                    logger.warning(
                        f"Failed to parse {key} from match '{match.group(1)}'"
                    )
                    break
        if key not in results:
            logger.error(f"{key} not found on page")
            results[key] = None
    return results


__all__ = ["download_html", "parse_patterns"]
