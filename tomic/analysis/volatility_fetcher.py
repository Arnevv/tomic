"""Helper functions for retrieving volatility metrics."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import math
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

import aiohttp

from tomic.api.base_client import BaseIBApp
from tomic.api.ib_connection import connect_ib
from tomic.config import VixConfig, VixJsonApiConfig, get as cfg_get
from tomic.logutils import logger
from tomic.utils import today
from tomic.webdata.utils import to_float

try:  # pragma: no cover - optional dependency during tests
    from ibapi.contract import Contract
except Exception:  # pragma: no cover - tests without ibapi
    Contract = None  # type: ignore[assignment]

try:  # pragma: no cover - optional dependency during tests
    from ibapi.ticktype import TickTypeEnum
except Exception:  # pragma: no cover - fallback constants used in tests
    class _TickTypeEnumFallback:  # type: ignore[too-few-public-methods]
        LAST = 4
        CLOSE = 9
        DELAYED_LAST = 68
        DELAYED_CLOSE = 75
        MARK_PRICE = 37

    TickTypeEnum = _TickTypeEnumFallback()  # type: ignore[assignment]


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

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MEMORY_CACHE_TTL = 60.0
_VIX_CACHE: dict[str, Any] = {}

_VixFetcherResult = Tuple[Optional[float], Optional[str], Optional[str]]

_DEFAULT_VIX_SETTINGS = VixConfig()


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


def _vix_settings() -> VixConfig:
    raw = cfg_get("VIX", None)
    if isinstance(raw, VixConfig):
        return raw
    if isinstance(raw, dict):
        return VixConfig(**raw)

    order_raw = cfg_get("VIX_SOURCE_ORDER", _DEFAULT_VIX_SETTINGS.provider_order)
    if isinstance(order_raw, str):
        order = [part.strip() for part in order_raw.split(",") if part.strip()]
    elif isinstance(order_raw, (list, tuple)):
        order = [str(part) for part in order_raw]
    else:
        order = list(_DEFAULT_VIX_SETTINGS.provider_order)

    return VixConfig(
        provider_order=order or list(_DEFAULT_VIX_SETTINGS.provider_order),
        daily_store=_DEFAULT_VIX_SETTINGS.daily_store,
        http_timeout_sec=float(cfg_get("VIX_TIMEOUT", _DEFAULT_VIX_SETTINGS.http_timeout_sec)),
        http_retries=int(cfg_get("VIX_RETRIES", _DEFAULT_VIX_SETTINGS.http_retries)),
    )


def _daily_store_path(settings: VixConfig) -> Path:
    path = Path(settings.daily_store)
    if not path.is_absolute():
        path = _REPO_ROOT / path
    return path


def _load_daily_vix(settings: VixConfig) -> Tuple[Optional[float], Optional[str]]:
    path = _daily_store_path(settings)
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            last_row: dict[str, str] | None = None
            for row in reader:
                last_row = row
    except FileNotFoundError:
        return None, None
    except Exception as exc:  # pragma: no cover - unexpected file errors
        logger.warning(f"Failed to read VIX daily cache at {path}: {exc}")
        return None, None

    if not last_row:
        return None, None

    if last_row.get("date") != today().isoformat():
        return None, None

    value = to_float(last_row.get("vix"))
    if value is None:
        return None, None
    return value, last_row.get("source")


def _save_daily_vix(settings: VixConfig, value: float, source: str | None) -> None:
    path = _daily_store_path(settings)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not path.exists()
        with path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["date", "vix", "source", "ts"])
            if write_header:
                writer.writeheader()
            writer.writerow(
                {
                    "date": today().isoformat(),
                    "vix": f"{value:.6f}",
                    "source": source or "",
                    "ts": datetime.now(timezone.utc).isoformat(),
                }
            )
    except Exception as exc:  # pragma: no cover - filesystem errors
        logger.warning(f"Failed to persist VIX daily cache at {path}: {exc}")


def _extract_json_field(payload: Any, path: str | None) -> Any:
    if not path:
        return payload
    current: Any = payload
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            try:
                idx = int(part)
            except (TypeError, ValueError):
                return None
            if 0 <= idx < len(current):
                current = current[idx]
            else:
                return None
        else:
            return None
    return current


def _http_timeout() -> float:
    settings = _vix_settings()
    return max(0.1, float(settings.http_timeout_sec))


def _http_retries() -> int:
    settings = _vix_settings()
    return max(0, int(settings.http_retries))


def _ib_timeout() -> float:
    settings = _vix_settings()
    return max(0.5, float(settings.ib_timeout_sec))


async def _request_text(
    url: str, *, headers: Optional[dict[str, str]] = None
) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(text, error)`` fetched from ``url`` with VIX retry policy."""

    timeout = _http_timeout()
    retries = _http_retries()
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


def _accepted_tick_types() -> set[int]:
    values = {
        getattr(TickTypeEnum, "LAST", None),
        getattr(TickTypeEnum, "CLOSE", None),
        getattr(TickTypeEnum, "DELAYED_LAST", None),
        getattr(TickTypeEnum, "DELAYED_CLOSE", None),
        getattr(TickTypeEnum, "MARK_PRICE", None),
    }
    return {int(v) for v in values if isinstance(v, int)}


def _serialise_contract(contract: Any) -> Dict[str, Any]:
    """Return a serialisable view of a contract for logging purposes."""

    fields = (
        "conId",
        "symbol",
        "secType",
        "currency",
        "exchange",
        "primaryExchange",
        "lastTradeDateOrContractMonth",
        "tradingClass",
        "localSymbol",
    )
    payload: Dict[str, Any] = {}
    for field in fields:
        if hasattr(contract, field):
            value = getattr(contract, field)
            if value not in (None, ""):
                payload[field] = value
    return payload


class _IbkrVixClient(BaseIBApp):
    """Light-weight client for requesting a single VIX snapshot."""

    _ACCEPTED_TICKS = _accepted_tick_types()

    def __init__(self) -> None:
        super().__init__()
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._value: Optional[float] = None
        self._error: Optional[str] = None
        self._req_counter = 9000
        self._active_req: Optional[int] = None

    def _next_id(self) -> int:
        self._req_counter += 1
        return self._req_counter

    def _store_value(self, value: float) -> None:
        with self._lock:
            self._value = value
        self._event.set()

    def _store_error(self, message: str) -> None:
        with self._lock:
            self._error = message
        self._event.set()

    def tickPrice(self, reqId: int, tickType: int, price: float, attrib) -> None:  # noqa: N802 - IB API
        if reqId != self._active_req:
            return
        if tickType not in self._ACCEPTED_TICKS:
            return
        try:
            value = float(price)
        except (TypeError, ValueError):
            return
        if not math.isfinite(value) or value <= 0:
            return
        self._store_value(value)

    def tickSnapshotEnd(self, reqId: int) -> None:  # noqa: N802 - IB API
        if reqId != self._active_req:
            return
        with self._lock:
            if self._value is None and not self._error:
                self._error = "snapshot ended without price"
        self._event.set()

    def error(  # type: ignore[override]
        self,
        reqId: int,
        errorTime: int,
        errorCode: int,
        errorString: str,
        advancedOrderRejectJson: str = "",
    ) -> None:
        super().error(reqId, errorTime, errorCode, errorString, advancedOrderRejectJson)
        if reqId in {-1, self._active_req}:
            self._store_error(errorString)

    def request_snapshot(self, contract: Any, timeout: float) -> Tuple[Optional[float], Optional[str]]:
        timeout = max(timeout, 0.5)
        last_error: Optional[str] = None
        for data_type in (1, 2, 3, 4):
            try:
                self.reqMarketDataType(data_type)
            except Exception:  # pragma: no cover - unavailable in some modes
                pass
            req_id = self._next_id()
            self._active_req = req_id
            self._event.clear()
            with self._lock:
                self._value = None
                self._error = None
            try:
                payload = {
                    "contract": _serialise_contract(contract),
                    "generic_ticks": "",
                    "snapshot": True,
                    "regulatory_snapshot": False,
                    "options": [],
                    "market_data_type": data_type,
                    "req_id": req_id,
                }
                logger.debug(
                    "Requesting VIX snapshot via IBKR: %s",
                    payload,
                )
                self.reqMktData(req_id, contract, "", True, False, [])
            except Exception as exc:  # pragma: no cover - network failures
                last_error = str(exc)
                self._active_req = None
                continue
            if self._event.wait(timeout):
                with self._lock:
                    if self._value is not None:
                        return self._value, None
                    last_error = self._error or "no data"
            else:
                last_error = "timeout"
            try:
                self.cancelMktData(req_id)
            except Exception:  # pragma: no cover - clean-up best effort
                pass
            self._active_req = None
            if self._value is not None:
                return self._value, None
        return None, last_error


def _ibkr_source_label(exchange: str | None) -> str:
    if not exchange:
        return "ibkr"
    return f"ibkr:{exchange.lower()}"


def _parse_ibkr_exchange(raw_exchange: str) -> tuple[str, Optional[str]]:
    """Return (exchange, primary_exchange) for an IBKR venue string."""

    parts = raw_exchange.split("@", 1)
    exchange = parts[0].strip().upper()
    primary = parts[1].strip().upper() if len(parts) == 2 else None
    return exchange, primary if primary else None


def _fetch_vix_from_ibkr_sync(settings: VixConfig) -> _VixFetcherResult:
    if Contract is None:
        return None, None, "ibapi not installed"

    timeout = _ib_timeout()
    host = cfg_get("IB_HOST", "127.0.0.1")
    paper_mode = bool(cfg_get("IB_PAPER_MODE", True))
    port_key = "IB_PORT" if paper_mode else "IB_LIVE_PORT"
    default_port = 7497 if paper_mode else 7496
    port = int(cfg_get(port_key, default_port))
    client_id = int(cfg_get("IB_MARKETDATA_CLIENT_ID", 901))

    app = _IbkrVixClient()
    logger.debug(
        "Connecting to IBKR for VIX host=%s port=%s client_id=%s timeout=%ss",
        host,
        port,
        client_id,
        timeout,
    )

    try:
        connect_ib(
            client_id=client_id,
            host=host,
            port=port,
            timeout=int(max(1, round(timeout))),
            unique=True,
            app=app,
        )
    except Exception as exc:  # pragma: no cover - network failures
        logger.warning(f"IBKR VIX connection failed: {exc}")
        return None, None, str(exc)

    last_error: Optional[str] = None
    try:
        exchanges = settings.ib_exchanges or ["CBOE", "CBOEIND"]
        for raw_exchange in exchanges:
            exchange, primary_exchange = _parse_ibkr_exchange(raw_exchange)
            try:
                contract = Contract()
            except Exception as exc:  # pragma: no cover - contract creation
                return None, None, f"failed to build contract: {exc}"
            contract.symbol = "VIX"
            contract.secType = "IND"
            contract.currency = "USD"
            contract.exchange = exchange
            if primary_exchange is not None:
                contract.primaryExchange = primary_exchange
            logger.debug(
                "Prepared IBKR contract for VIX: %s",
                _serialise_contract(contract),
            )
            value, error = app.request_snapshot(contract, timeout)
            if value is not None:
                return value, _ibkr_source_label(exchange), None
            if error:
                last_error = error
        return None, None, last_error or "no data"
    finally:
        try:
            app.disconnect()
        except Exception:  # pragma: no cover - best effort cleanup
            pass


def _json_api_source_label(config: VixJsonApiConfig | None) -> str:
    if config and config.name:
        return config.name
    return "json_api"


def _parse_csv_payload(text: str, field: str | None) -> Optional[float]:
    reader = csv.DictReader(io.StringIO(text))
    try:
        row = next(reader)
    except StopIteration:
        return None
    if not row:
        return None
    if field:
        return to_float(row.get(field))
    for value in row.values():
        parsed = to_float(value)
        if parsed is not None:
            return parsed
    return None


def _parse_json_payload(text: str, field: str | None) -> Optional[float]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error(f"Failed to decode VIX JSON payload: {exc}")
        return None
    value = _extract_json_field(payload, field) if field else payload
    if isinstance(value, dict):
        for candidate in value.values():
            parsed = to_float(candidate)
            if parsed is not None:
                return parsed
        return None
    if isinstance(value, list):
        for item in value:
            parsed = to_float(item)
            if parsed is not None:
                return parsed
        return None
    return to_float(value)


async def _fetch_vix_from_json_api() -> _VixFetcherResult:
    settings = _vix_settings()
    api_cfg = settings.json_api
    if not api_cfg or not api_cfg.url:
        return None, None, "json api not configured"
    headers = api_cfg.headers or None
    text, error = await _request_text(api_cfg.url, headers=headers)
    if text is None:
        return None, None, error
    fmt = (api_cfg.format or "json").lower()
    if fmt == "csv":
        value = _parse_csv_payload(text, api_cfg.field)
        if value is None:
            return None, None, "csv parse error"
    else:
        value = _parse_json_payload(text, api_cfg.field)
        if value is None:
            missing = f"field '{api_cfg.field}'" if api_cfg.field else "value"
            return None, None, f"json parse error ({missing})"
    return value, _json_api_source_label(api_cfg), None


async def _fetch_vix_from_yahoo_html() -> _VixFetcherResult:
    html, error = await _request_text(
        YAHOO_VIX_HTML_URL, headers={"User-Agent": "Mozilla/5.0"}
    )
    if html is None:
        return None, None, error
    blocker = _detect_blocker(html)
    if blocker:
        logger.warning(
            f"Yahoo HTML response appears blocked by '{blocker}' keyword"
        )
        return None, None, f"blocked by {blocker} page"
    value = _parse_vix_from_yahoo(html)
    if value is not None:
        logger.debug(f"Yahoo Finance VIX scrape result: {value}")
        return value, "yahoo_html", None
    logger.error(
        f"Failed to parse VIX payload from Yahoo HTML at {YAHOO_VIX_HTML_URL}"
    )
    return None, None, "parse error"


async def _fetch_vix_from_google_html() -> _VixFetcherResult:
    html, error = await _request_text(
        GOOGLE_VIX_HTML_URL, headers={"User-Agent": "Mozilla/5.0"}
    )
    if html is None:
        return None, None, error
    blocker = _detect_blocker(html)
    if blocker:
        logger.warning(
            f"Google HTML response appears blocked by '{blocker}' keyword"
        )
        return None, None, f"blocked by {blocker} page"
    value = _parse_vix_from_google(html)
    if value is not None:
        logger.debug(f"Google Finance VIX scrape result: {value}")
        return value, "google_html", None
    logger.error(
        f"Failed to parse VIX payload from Google HTML at {GOOGLE_VIX_HTML_URL}"
    )
    return None, None, "parse error"


async def _fetch_vix_from_barchart_html() -> _VixFetcherResult:
    html, error = await _request_text(
        BARCHART_VIX_HTML_URL, headers={"User-Agent": "Mozilla/5.0"}
    )
    if html is None:
        return None, None, error
    blocker = _detect_blocker(html)
    if blocker:
        logger.warning(
            f"Barchart HTML response appears blocked by '{blocker}' keyword"
        )
        return None, None, f"blocked by {blocker} page"
    value = _parse_vix_from_barchart(html)
    if value is not None:
        logger.debug(f"Barchart VIX scrape result: {value}")
        return value, "barchart_html", None
    logger.error(
        f"Failed to parse VIX payload from Barchart HTML at {BARCHART_VIX_HTML_URL}"
    )
    return None, None, "parse error"


async def _fetch_vix_from_yahoo_json() -> _VixFetcherResult:
    text, error = await _request_text(
        YAHOO_VIX_JSON_URL,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        },
    )
    if text is None:
        return None, None, error
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error(f"Failed to decode Yahoo JSON payload: {exc}")
        return None, None, "invalid json"
    try:
        result = payload["quoteResponse"]["result"][0]
    except (KeyError, IndexError, TypeError) as exc:
        logger.error(f"Unexpected Yahoo JSON payload shape: {exc}")
        return None, None, "unexpected json shape"
    value = to_float(result.get("regularMarketPrice"))
    if value is not None:
        logger.debug(f"Yahoo JSON VIX result: {value}")
        return value, "yahoo_json", None
    logger.error("Yahoo JSON payload missing regularMarketPrice")
    return None, None, "missing regularMarketPrice"


async def _fetch_vix_from_ibkr() -> _VixFetcherResult:
    loop = asyncio.get_running_loop()
    settings = _vix_settings()
    return await loop.run_in_executor(None, _fetch_vix_from_ibkr_sync, settings)


async def _fetch_vix_manual() -> _VixFetcherResult:
    if not sys.stdin or not sys.stdin.isatty():
        return None, None, "stdin not interactive"
    try:
        from tomic.cli.vix_prompt import prompt_manual_vix
    except Exception as exc:  # pragma: no cover - optional CLI dependency
        logger.error(f"Manual VIX prompt unavailable: {exc}")
        return None, None, "manual prompt unavailable"

    loop = asyncio.get_running_loop()
    try:
        value = await loop.run_in_executor(None, prompt_manual_vix)
    except Exception as exc:  # pragma: no cover - user input errors
        logger.error(f"Manual VIX prompt failed: {exc}")
        return None, None, str(exc)
    if value is None:
        return None, None, "user skipped"
    return value, "manual", None


_VIX_SOURCE_FETCHERS: dict[
    str, Callable[[], Awaitable[_VixFetcherResult]]
] = {
    "ibkr": _fetch_vix_from_ibkr,
    "json_api": _fetch_vix_from_json_api,
    "yahoo_json": _fetch_vix_from_yahoo_json,
    "barchart_html": _fetch_vix_from_barchart_html,
    "yahoo_html": _fetch_vix_from_yahoo_html,
    "google_html": _fetch_vix_from_google_html,
    "manual": _fetch_vix_manual,
}


def _update_memory_cache(value: Optional[float], source: Optional[str]) -> None:
    _VIX_CACHE.update({"value": value, "source": source, "ts": time.monotonic()})


def _memory_cache_entry() -> Tuple[Optional[float], Optional[str]]:
    if not _VIX_CACHE:
        return None, None
    ts = _VIX_CACHE.get("ts")
    if ts is None:
        return _VIX_CACHE.get("value"), _VIX_CACHE.get("source")
    if time.monotonic() - float(ts) <= _MEMORY_CACHE_TTL:
        return _VIX_CACHE.get("value"), _VIX_CACHE.get("source")
    return None, None


async def _get_vix_value() -> Tuple[Optional[float], Optional[str]]:
    """Return cached VIX value or fetch according to configured order."""

    cached_value, cached_source = _memory_cache_entry()
    if cached_value is not None or ("value" in _VIX_CACHE):
        return cached_value, cached_source

    settings = _vix_settings()
    daily_value, daily_source = _load_daily_vix(settings)
    if daily_value is not None:
        _update_memory_cache(daily_value, daily_source)
        return daily_value, daily_source

    order = settings.provider_order or list(_DEFAULT_VIX_SETTINGS.provider_order)
    errors: dict[str, str] = {}
    for source_name in order:
        fetcher = _VIX_SOURCE_FETCHERS.get(source_name)
        if fetcher is None:
            logger.warning(f"Unknown VIX source '{source_name}' in configuration")
            errors[source_name] = "unknown source"
            continue
        try:
            value, provider_label, error = await fetcher()
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception(f"VIX provider '{source_name}' failed unexpectedly: {exc}")
            errors[source_name] = str(exc)
            continue
        if value is not None:
            label = provider_label or source_name
            _update_memory_cache(value, label)
            _save_daily_vix(settings, value, label)
            return value, label
        if error:
            errors[source_name] = error

    logger.error(
        "Failed to retrieve VIX from any source: %s",
        "; ".join(f"{src} -> {msg}" for src, msg in errors.items()) or "no sources",
    )
    _update_memory_cache(None, None)
    return None, None


_VIX_SYMBOL = "VIX"


async def fetch_volatility_metrics_async(symbol: str) -> Dict[str, float]:
    """Asynchronously fetch volatility metrics for ``symbol``.

    External scraping for implied-volatility metrics has been removed. The
    remaining data focuses solely on retrieving the VIX value via the normal
    provider chain.
    """

    metrics: Dict[str, float] = {}
    vix_value, vix_source = await _get_vix_value()
    if vix_value is not None:
        metrics["vix"] = vix_value
    if vix_source:
        metrics["vix_source"] = vix_source
    logger.debug(
        "volatility_metrics symbol=%s vix=%s vix_src=%s",
        _VIX_SYMBOL,
        metrics.get("vix"),
        vix_source,
    )
    return metrics


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
    "fetch_volatility_metrics",
    "fetch_volatility_metrics_async",
]
