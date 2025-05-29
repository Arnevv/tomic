import logging
import re
from datetime import datetime, timezone
from typing import Dict, List

from tomic.config import get as cfg_get

from tomic.analysis.get_iv_rank import _download_html
from vol_cone_db import store_volatility_snapshot


IV_PATTERNS = {
    "iv_rank": [
        r"IV\s*&nbsp;?Rank:</span>\s*<span><strong>([0-9]+(?:\.[0-9]+)?)%",
        r"IV\s*Rank[^0-9]*([0-9]+(?:\.[0-9]+)?)",
    ],
    "implied_volatility": [
        r"Implied\s*&nbsp;?Volatility:</span>.*?<strong>([0-9]+(?:\.[0-9]+)?)%",
        r"Implied\s+Volatility[^0-9]*([0-9]+(?:\.[0-9]+)?)%",
    ],
}

EXTRA_PATTERNS = {
    "spot_price": [
        r"\"lastPrice\":\s*([0-9]+(?:\.[0-9]+)?)",
        r"Last Price[^0-9]*([0-9]+(?:\.[0-9]+)?)",
    ],
    "hv30": [
        r"30[- ]Day Historical Volatility[^0-9]*([0-9]+(?:\.[0-9]+)?)%",
        r"HV\s*30[^0-9]*([0-9]+(?:\.[0-9]+)?)%",
        r"Historic\s*&nbsp;?Volatility[^0-9]*([0-9]+(?:\.[0-9]+)?)%",
        r"HV:\s*</span>\s*</span>\s*<span><strong>([0-9]+(?:\.[0-9]+)?)%",
    ],
    "skew": [
        r"Skew[^0-9-]*(-?[0-9]+(?:\.[0-9]+)?)",
    ],
}


def _parse_patterns(patterns: Dict[str, List[str]], html: str) -> Dict[str, float]:
    """Return a dict with parsed values using the provided patterns."""
    results: Dict[str, float] = {}
    for key, pats in patterns.items():
        for pat in pats:
            match = re.search(pat, html, re.IGNORECASE | re.DOTALL)
            if match:
                try:
                    results[key] = float(match.group(1))
                    break
                except ValueError:
                    break
        if key not in results:
            results[key] = None
    return results


def fetch_volatility_metrics(symbol: str) -> Dict[str, float]:
    """Fetch spot, IV30, HV30, IV rank and skew for a symbol."""
    html = _download_html(symbol)
    iv_data = _parse_patterns(IV_PATTERNS, html)
    extra_data = _parse_patterns(EXTRA_PATTERNS, html)
    data = {**iv_data, **extra_data}
    return data


def snapshot_symbols(symbols: List[str]) -> None:
    for sym in symbols:
        logging.info("Fetching metrics for %s", sym)
        try:
            metrics = fetch_volatility_metrics(sym)
        except Exception as exc:  # pragma: no cover - network dependent
            logging.error("Failed for %s: %s", sym, exc)
            continue
        record = {
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "symbol": sym,
            "spot": metrics.get("spot_price"),
            "iv30": metrics.get("implied_volatility"),
            "hv30": metrics.get("hv30"),
            "iv_rank": metrics.get("iv_rank"),
            "skew": metrics.get("skew"),
        }
        store_volatility_snapshot(record)
        logging.info("Stored snapshot for %s", sym)


def main(argv: List[str] | None = None) -> None:
    if argv is None:
        argv = []
    if argv:
        symbols = [s.upper() for s in argv]
    else:
        symbols = [s.upper() for s in cfg_get("DEFAULT_SYMBOLS", [])]
    snapshot_symbols(symbols)


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    main(sys.argv[1:])
