import logging
import re
import sys
import urllib.request


def fetch_iv_rank(symbol: str = "SPY") -> float:
    """Fetch IV Rank for the given symbol from Optioncharts."""
    url = f"https://optioncharts.io/options/{symbol}"
    logging.debug("Requesting URL: %s", url)

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
    )

    with urllib.request.urlopen(req) as response:
        html = response.read().decode("utf-8", errors="ignore")
    logging.debug("Downloaded %d characters", len(html))

    # Try patterns for 'IV30 % Rank' first, then generic 'IV Rank'
    patterns = [
        r"IV30\s*%?\s*Rank[^0-9]*([0-9]+(?:\.[0-9]+)?)",
        r"IV\s*Rank[^0-9]*([0-9]+(?:\.[0-9]+)?)",
    ]

    for pat in patterns:
        match = re.search(pat, html, re.IGNORECASE)
        if match:
            try:
                iv = float(match.group(1))
                logging.debug("Matched pattern '%s' -> %s", pat, iv)
                return iv
            except ValueError:
                logging.warning("Failed to parse IV Rank from match '%s'", match.group(1))
                break

    raise ValueError("IV Rank not found on page")


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    symbol = (argv[0] if argv else input("Ticker (default SPY): ")).strip().upper() or "SPY"
    logging.info("Fetching IV Rank for %s", symbol)

    try:
        iv_rank = fetch_iv_rank(symbol)
        print(f"IV Rank for {symbol}: {iv_rank}")
    except Exception as exc:
        logging.error("Error fetching IV Rank: %s", exc)


if __name__ == "__main__":
    main()
