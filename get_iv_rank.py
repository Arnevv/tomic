import logging
import re
import sys
import urllib.request


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

    patterns = {
        "iv_rank": [
            r"IV\s*&nbsp;?Rank:</span>\s*<span><strong>([0-9]+(?:\.[0-9]+)?)%",
            r"IV\s*Rank[^0-9]*([0-9]+(?:\.[0-9]+)?)",
        ],
        "implied_volatility": [
            r"Implied\s*&nbsp;?Volatility:</span>.*?<strong>([0-9]+(?:\.[0-9]+)?)%",
            r"Implied\s+Volatility[^0-9]*([0-9]+(?:\.[0-9]+)?)%",
        ],
        "iv_percentile": [
            r"IV\s*&nbsp;?Percentile:</span>.*?<strong>([0-9]+(?:\.[0-9]+)?)%",
            r"IV\s*Pctl:</span>.*?<strong>([0-9]+(?:\.[0-9]+)?)%",
        ],
    }

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
    if argv is None:
        argv = sys.argv[1:]

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    symbol = (argv[0] if argv else input("Ticker (default SPY): ")).strip().upper() or "SPY"
    logging.info("Fetching IV metrics for %s", symbol)

    try:
        metrics = fetch_iv_metrics(symbol)
        iv_rank = metrics.get("iv_rank")
        implied_vol = metrics.get("implied_volatility")
        iv_pct = metrics.get("iv_percentile")

        print(f"IV Rank for {symbol}: {iv_rank}")
        print(f"Implied Volatility: {implied_vol}")
        print(f"IV Percentile: {iv_pct}")
    except Exception as exc:
        logging.error("Error fetching IV metrics: %s", exc)


if __name__ == "__main__":
    main()
