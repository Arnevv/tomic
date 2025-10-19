"""Helper functions for retrieving volatility metrics."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Awaitable, Callable, Dict, Optional, Tuple

import aiohttp

from tomic.analysis.iv_patterns import EXTRA_PATTERNS, IV_PATTERNS
from tomic.config import get as cfg_get
from tomic.logutils import logger
from tomic.webdata.utils import download_html, download_html_async, parse_patterns, to_float


GOOGLE_VIX_HTML_URL = "https://www.google.com/finance/quote/VIX:INDEXCBOE"
_GOOGLE_VIX_PATTERNS = [
    r"YMlKec\s+fxKbKc\">\s*([0-9]+(?:[\.,][0-9]+)?)<",
    r"data-last-price=\"([0-9]+(?:[\.,][0-9]+)?)\"",
    r"\"price\"\s*:\s*\{[^}]*\"raw\"\s*:\s*([0-9]+(?:[\.,][0-9]+)?)",
]

YAHOO_VIX_HTML_URL = "https://finance.yahoo.com/quote/%5EVIX/"
_YAHOO_VIX_PATTERNS = [
    r"\"regularMarketPrice\"\s*:\s*\{\s*\"raw\"\s*:\s*([0-9]+(?:[\.,][0-9]+)?)",
    r"data-symbol=\"\^?VIX\"[^>]*data-field=\"regularMarketPrice\"[^>]*value=\"([0-9]+(?:[\.,][0-9]+)?)\"",
    r"data-field=\"regularMarketPrice\"[^>]*data-symbol=\"\^?VIX\"[^>]*value=\"([0-9]+(?:[\.,][0-9]+)?)\"",
    r"data-field=\"regularMarketPrice\"[^>]*data-symbol=\"\^?VIX\"[^>]*>([0-9]+(?:[\.,][0-9]+)?)<",
]

BARCHART_VIX_HTML_URL = "https://www.barchart.com/stocks/quotes/$VIX/overview"
_BARCHART_VIX_PATTERNS = [
    r"data-test=\"instrument-price-last\"[^>]*>([0-9]+(?:[\.,][0-9]+)?)<",
    r"\"lastPrice\"\s*:\s*\"([0-9]+(?:[\.,][0-9]+)?)\"",
]

YAHOO_VIX_JSON_URL = (
    "https://query1.finance.yahoo.com/v7/finance/quote?symbols=%5EVIX"
)

_BLOCKER_KEYWORDS = ("consent", "captcha", "enable javascript")

_VIX_CACHE: dict[str, Optional[str | float]] = {}


def _parse_vix_from_google(html: str) -> Optional[float]:
    """Extract the VIX value from Google Finance HTML."""

    for pattern in _GOOGLE_VIX_PATTERNS:
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if match:
            value = to_float(match.group(1))
            if value is not None:
                logger.debug(
                    f"Parsed Google VIX value {value} using pattern '{pattern}'"
                )
                return value
            logger.warning(
                f"Failed to parse numeric VIX value '{match.group(1)}' from Google HTML"
            )
            return None
    return None


def _parse_vix_from_yahoo(html: str) -> Optional[float]:
    """Extract the VIX value from Yahoo Finance HTML."""

    for pattern in _YAHOO_VIX_PATTERNS:
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if match:
            value = to_float(match.group(1))
            if value is not None:
                logger.debug(
                    f"Parsed Yahoo VIX value {value} using pattern '{pattern}'"
                )
                return value
            logger.warning(
                f"Failed to parse numeric VIX value '{match.group(1)}' from Yahoo HTML"
            )
    return None


def _parse_vix_from_barchart(html: str) -> Optional[float]:
    """Extract the VIX value from the Barchart overview page."""

    for pattern in _BARCHART_VIX_PATTERNS:
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if match:
            value = to_float(match.group(1))
            if value is not None:
                logger.debug(
                    f"Parsed Barchart VIX value {value} using pattern '{pattern}'"
                )
                return value
            logger.warning(
                f"Failed to parse numeric VIX value '{match.group(1)}' from Barchart HTML"
            )
            break
    return None


def _detect_blocker(html: str) -> Optional[str]:
    """Return keyword that indicates a consent/captcha wall."""

    lowered = html.lower()
    for keyword in _BLOCKER_KEYWORDS:
        if keyword in lowered:
            return keyword
    return None


def _vix_timeout() -> float:
    return float(cfg_get("VIX_TIMEOUT", 3))


def _vix_retries() -> int:
    return int(cfg_get("VIX_RETRIES", 1))


def _vix_source_order() -> list[str]:
    raw = cfg_get(
        "VIX_SOURCE_ORDER",
        ["yahoo_json", "google_html", "yahoo_html"],
    )
    if isinstance(raw, str):
        order = [part.strip() for part in raw.split(",") if part.strip()]
    elif isinstance(raw, (list, tuple)):
        order = [str(part) for part in raw]
    else:
        order = ["yahoo_json", "google_html", "yahoo_html"]
    if "barchart_html" not in order:
        order.insert(0, "barchart_html")
    return order


async def _request_text(url: str, *, headers: Optional[dict[str, str]] = None) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(text, error)`` fetched from ``url`` with VIX retry policy."""

    timeout = _vix_timeout()
    retries = max(0, _vix_retries())
    attempts = retries + 1
    collected_errors: list[str] = []
    for attempt in range(1, attempts + 1):
        logger.debug(
            f"Requesting VIX source {url} (attempt {attempt}/{attempts})"
        )
        try:
            timeout_obj = aiohttp.ClientTimeout(total=timeout)
            async with aiohttp.ClientSession(timeout=timeout_obj) as session:
                async with session.get(url, headers=headers) as response:
                    response.raise_for_status()
                    return await response.text(), None
        except Exception as exc:  # pragma: no cover - network failures
            message = str(exc)
            collected_errors.append(message)
            logger.warning(f"VIX request attempt {attempt} failed: {message}")
            if attempt != attempts:
                await asyncio.sleep(0.5)
    return None, "; ".join(collected_errors) if collected_errors else "Unknown error"


async def _fetch_vix_from_yahoo_html() -> Tuple[Optional[float], Optional[str]]:
    html, error = await _request_text(
        YAHOO_VIX_HTML_URL, headers={"User-Agent": "Mozilla/5.0"}
    )
    if html is None:
        return None, error
    blocker = _detect_blocker(html)
    if blocker:
        logger.warning(
            f"Yahoo HTML response appears blocked by '{blocker}' keyword"
        )
        return None, f"blocked by {blocker} page"
    value = _parse_vix_from_yahoo(html)
    if value is not None:
        logger.debug(f"Yahoo Finance VIX scrape result: {value}")
        return value, None
    logger.error(
        f"Failed to parse VIX payload from Yahoo HTML at {YAHOO_VIX_HTML_URL}"
    )
    return None, "parse error"


async def _fetch_vix_from_google_html() -> Tuple[Optional[float], Optional[str]]:
    html, error = await _request_text(
        GOOGLE_VIX_HTML_URL, headers={"User-Agent": "Mozilla/5.0"}
    )
    if html is None:
        return None, error
    blocker = _detect_blocker(html)
    if blocker:
        logger.warning(
            f"Google HTML response appears blocked by '{blocker}' keyword"
        )
        return None, f"blocked by {blocker} page"
    value = _parse_vix_from_google(html)
    if value is not None:
        logger.debug(f"Google Finance VIX scrape result: {value}")
        return value, None
    logger.error(
        f"Failed to parse VIX payload from Google HTML at {GOOGLE_VIX_HTML_URL}"
    )
    return None, "parse error"


async def _fetch_vix_from_barchart_html() -> Tuple[Optional[float], Optional[str]]:
    html, error = await _request_text(
        BARCHART_VIX_HTML_URL, headers={"User-Agent": "Mozilla/5.0"}
    )
    if html is None:
        return None, error
    blocker = _detect_blocker(html)
    if blocker:
        logger.warning(
            f"Barchart HTML response appears blocked by '{blocker}' keyword"
        )
        return None, f"blocked by {blocker} page"
    value = _parse_vix_from_barchart(html)
    if value is not None:
        logger.debug(f"Barchart VIX scrape result: {value}")
        return value, None
    logger.error(
        f"Failed to parse VIX payload from Barchart HTML at {BARCHART_VIX_HTML_URL}"
    )
    return None, "parse error"


async def _fetch_vix_from_yahoo_json() -> Tuple[Optional[float], Optional[str]]:
    text, error = await _request_text(
        YAHOO_VIX_JSON_URL,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        },
    )
    if text is None:
        return None, error
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error(f"Failed to decode Yahoo JSON payload: {exc}")
        return None, "invalid json"
    try:
        result = payload["quoteResponse"]["result"][0]
    except (KeyError, IndexError, TypeError) as exc:
        logger.error(f"Unexpected Yahoo JSON payload shape: {exc}")
        return None, "unexpected json shape"
    value = to_float(result.get("regularMarketPrice"))
    if value is not None:
        logger.debug(f"Yahoo JSON VIX result: {value}")
        return value, None
    logger.error("Yahoo JSON payload missing regularMarketPrice")
    return None, "missing regularMarketPrice"


_VIX_SOURCE_FETCHERS: dict[str, Callable[[], Awaitable[Tuple[Optional[float], Optional[str]]]]] = {
    "barchart_html": _fetch_vix_from_barchart_html,
    "yahoo_json": _fetch_vix_from_yahoo_json,
    "google_html": _fetch_vix_from_google_html,
    "yahoo_html": _fetch_vix_from_yahoo_html,
}


async def _get_vix_value() -> Tuple[Optional[float], Optional[str]]:
    """Return cached VIX value or fetch according to configured order."""

    cached_value = _VIX_CACHE.get("value") if _VIX_CACHE else None
    cached_source = _VIX_CACHE.get("source") if _VIX_CACHE else None
    if cached_value is not None or ("value" in _VIX_CACHE):
        return cached_value, cached_source  # type: ignore[return-value]

    order = _vix_source_order()
    errors: dict[str, str] = {}
    for source in order:
        fetcher = _VIX_SOURCE_FETCHERS.get(source)
        if fetcher is None:
            logger.warning(f"Unknown VIX source '{source}' in configuration")
            errors[source] = "unknown source"
            continue
        value, err = await fetcher()
        if value is not None:
            _VIX_CACHE.update({"value": value, "source": source})
            return value, source
        if err:
            errors[source] = err

    logger.error(
        "Failed to retrieve VIX from any source: %s",
        "; ".join(f"{src} -> {msg}" for src, msg in errors.items()) or "no sources",
    )
    _VIX_CACHE.update({"value": None, "source": None})
    return None, None


async def fetch_volatility_metrics_async(symbol: str) -> Dict[str, float]:
    """Asynchronously fetch volatility metrics from the web."""
    html = await download_html_async(symbol)
    iv_data = parse_patterns(IV_PATTERNS, html)
    extra_data = parse_patterns(EXTRA_PATTERNS, html)
    vix_value, vix_source = await _get_vix_value()
    extra_data["vix"] = vix_value
    for key in ("iv_rank", "iv_percentile"):
        if iv_data.get(key) is not None:
            iv_data[key] /= 100
    merged = {**iv_data, **extra_data}
    logger.info(
        "volatility_metrics symbol=%s iv_rank=%s vix=%s source=%s",
        symbol,
        merged.get("iv_rank"),
        merged.get("vix"),
        vix_source,
    )
    return merged


def fetch_volatility_metrics(symbol: str) -> Dict[str, float]:
    """Return key volatility metrics for ``symbol``.

    Network errors are logged and result in an empty ``dict``.
    """
    try:
        return asyncio.run(fetch_volatility_metrics_async(symbol))
    except Exception as exc:  # pragma: no cover - network failures
        logger.error(f"Failed to fetch volatility metrics for {symbol}: {exc}")
        return {}


__all__ = [
    "download_html",
    "parse_patterns",
    "fetch_volatility_metrics",
    "fetch_volatility_metrics_async",
]
