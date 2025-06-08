"""Scrape daily volatility metrics from web sources."""

from typing import Dict, List

from tomic.logutils import logger

from tomic.config import get as cfg_get

from tomic.webdata.utils import download_html, parse_patterns
from tomic.analysis.iv_patterns import IV_PATTERNS, EXTRA_PATTERNS
from tomic.analysis.vol_snapshot import snapshot_symbols
from tomic.logutils import setup_logging


def fetch_volatility_metrics(symbol: str) -> Dict[str, float]:
    """Fetch spot, IV30, HV30, IV rank and skew for a symbol."""
    html = download_html(symbol)
    iv_data = parse_patterns(IV_PATTERNS, html)
    extra_data = parse_patterns(EXTRA_PATTERNS, html)
    data = {**iv_data, **extra_data}
    return data


def main(argv: List[str] | None = None) -> None:
    """Fetch daily volatility data for a list of symbols."""
    setup_logging()
    logger.info("🚀 Daily volatility scrape")
    if argv is None:
        argv = []
    if argv:
        symbols = [s.upper() for s in argv]
    else:
        symbols = [s.upper() for s in cfg_get("DEFAULT_SYMBOLS", [])]
    snapshot_symbols(symbols, fetch_volatility_metrics)
    logger.success(f"✅ Volatiliteitsscrape voltooid voor {len(symbols)} symbolen")


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
