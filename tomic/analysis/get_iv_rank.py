import logging
import re
import sys
import urllib.request

from tomic.analysis.iv_patterns import IV_PATTERNS
from tomic.logging import setup_logging


def _download_html(symbol: str) -> str:
    """Retrieve the volatility page HTML for the given symbol."""
    url = f"https://www.barchart.com/etfs-funds/quotes/{symbol}/volatility-charts"
    logging.debug("Requesting URL: %s", url)

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
    )

    with urllib.request.urlopen(req) as response:
        html = response.read().decode("utf-8", errors="ignore")
    logging.debug("Downloaded %d characters", len(html))
    return html


def fetch_iv_metrics(symbol: str = "SPY") -> dict:
    """Return IV Rank, Implied Volatility and IV Percentile for the symbol."""
    html = _download_html(symbol)

    patterns = IV_PATTERNS

    results = {}
    for key, pats in patterns.items():
        for pat in pats:
            match = re.search(pat, html, re.IGNORECASE | re.DOTALL)
            if match:
                try:
                    results[key] = float(match.group(1))
                    logging.debug("Matched pattern '%s' for %s -> %s", pat, key, results[key])
                    break
                except ValueError:
                    logging.warning("Failed to parse %s from match '%s'", key, match.group(1))
                    break
        if key not in results:
            logging.error("%s not found on page", key)
            results[key] = None

    return results


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

    symbol = (argv[0] if argv else input("Ticker (default SPY): ")).strip().upper() or "SPY"
    logging.info("Fetching IV metrics for %s", symbol)

    try:
        metrics = fetch_iv_metrics(symbol)
        iv_rank = metrics.get("iv_rank")
        implied_vol = metrics.get("implied_volatility")
        iv_pct = metrics.get("iv_percentile")

        logging.info("IV Rank for %s: %s", symbol, iv_rank)
        logging.info("Implied Volatility: %s", implied_vol)
        logging.info("IV Percentile: %s", iv_pct)
    except Exception as exc:
        logging.error("Error fetching IV metrics: %s", exc)


if __name__ == "__main__":
    main()
