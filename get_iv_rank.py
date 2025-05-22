import re
import urllib.request


def fetch_iv_rank(symbol="SPY"):
    """Fetch IV Rank for the given symbol from MarketChameleon."""
    url = f"https://marketchameleon.com/Overview/{symbol}/Summary/"
    with urllib.request.urlopen(url) as response:
        html = response.read().decode("utf-8", errors="ignore")

    # Search for a pattern like 'IV Rank 45%' or 'IV Rank 45.2'
    match = re.search(r"IV\s*Rank[^0-9]*([0-9]+(?:\.[0-9]+)?)", html, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    raise ValueError("IV Rank not found on page")


def main():
    symbol = input("Ticker (default SPY): ").strip().upper() or "SPY"
    try:
        iv_rank = fetch_iv_rank(symbol)
        print(f"IV Rank for {symbol}: {iv_rank}")
    except Exception as exc:
        print("Error fetching IV Rank:", exc)


if __name__ == "__main__":
    main()
