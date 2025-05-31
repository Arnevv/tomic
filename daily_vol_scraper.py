import re
from datetime import datetime, timezone
from typing import Dict, List

from tomic.logging import logger

from tomic.config import get as cfg_get

from tomic.analysis.get_iv_rank import _download_html
from tomic.analysis.iv_patterns import IV_PATTERNS, EXTRA_PATTERNS
from vol_cone_db import store_volatility_snapshot
from tomic.logging import setup_logging


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
        logger.info("Fetching metrics for %s", sym)
        try:
            metrics = fetch_volatility_metrics(sym)
        except Exception as exc:  # pragma: no cover - network dependent
            logger.error("Failed for %s: %s", sym, exc)
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
        logger.info("Stored snapshot for %s", sym)


def main(argv: List[str] | None = None) -> None:
    setup_logging()
    logger.info("🚀 Daily volatility scrape")
    if argv is None:
        argv = []
    if argv:
        symbols = [s.upper() for s in argv]
    else:
        symbols = [s.upper() for s in cfg_get("DEFAULT_SYMBOLS", [])]
    snapshot_symbols(symbols)
    logger.success("✅ Volatiliteitsscrape voltooid voor %d symbolen", len(symbols))


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
