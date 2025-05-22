import logging
import re
import sys
import urllib.request
from urllib.error import HTTPError, URLError


def fetch_iv_rank(symbol: str = "SPY", timeout: int = 10) -> float:
    """Fetch IV Rank for the given symbol from MarketChameleon."""
    url = f"https://marketchameleon.com/Overview/{symbol}/Summary/"
    logging.debug("Requesting %s", url)
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            html = response.read().decode("utf-8", errors="ignore")
            logging.debug("Received %d bytes of HTML", len(html))
    except HTTPError as err:
        logging.error("HTTP error while fetching %s: %s", symbol, err)
        raise
    except URLError as err:
        logging.error("Network error while fetching %s: %s", symbol, err)
        raise

    # Search for a pattern like 'IV Rank 45%' or 'IV Rank 45.2'
    match = re.search(r"IV\s*Rank[^0-9]*([0-9]+(?:\.[0-9]+)?)", html, re.IGNORECASE)
    if not match:
        logging.error("IV Rank not found on page")
        raise ValueError("IV Rank not found on page")
    iv_rank_str = match.group(1)
    logging.debug("IV Rank string parsed: %s", iv_rank_str)
    try:
        return float(iv_rank_str)
    except ValueError as exc:
        logging.error("Failed to convert IV Rank '%s' to float", iv_rank_str)
        raise ValueError("Failed to parse IV Rank") from exc


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    symbol = None
    if len(sys.argv) > 1:
        symbol = sys.argv[1].strip().upper()
    if not symbol:
        symbol = input("Ticker (default SPY): ").strip().upper() or "SPY"

    logging.info("Fetching IV Rank for %s", symbol)
    try:
        iv_rank = fetch_iv_rank(symbol)
        print(f"IV Rank for {symbol}: {iv_rank}")
    except Exception as exc:
        logging.error("Error fetching IV Rank: %s", exc)


if __name__ == "__main__":
    main()
