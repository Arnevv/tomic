import re
import sys
import urllib.request

from tomic.logging import logger

from typing import Dict, List, Optional

from tomic.analysis.iv_patterns import IV_PATTERNS
from tomic.logging import setup_logging


def parse_patterns(
    patterns: Dict[str, List[str]], html: str
) -> Dict[str, Optional[float]]:
    """Return a dict with parsed values using the provided patterns."""
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


def _download_html(symbol: str) -> str:
    """Retrieve the volatility page HTML for the given symbol."""
    url = f"https://www.barchart.com/etfs-funds/quotes/{symbol}/volatility-charts"
    logger.debug(f"Requesting URL: {url}")

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
    )

    with urllib.request.urlopen(req) as response:
        html = response.read().decode("utf-8", errors="ignore")
    logger.debug(f"Downloaded {len(html)} characters")
    return html


def fetch_iv_metrics(symbol: str = "SPY") -> Dict[str, Optional[float]]:
    """Return IV Rank, Implied Volatility and IV Percentile for the symbol."""
    html = _download_html(symbol)
    return parse_patterns(IV_PATTERNS, html)


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
