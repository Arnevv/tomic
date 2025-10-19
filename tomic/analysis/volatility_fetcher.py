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
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

import aiohttp

from zoneinfo import ZoneInfo

from tomic.api.ib_connection import connect_ib
from tomic.config import VixConfig, VixJsonApiConfig, get as cfg_get
from tomic.logutils import logger
from tomic.webdata.utils import to_float

try:  # pragma: no cover - optional dependency during tests
    from ibapi.contract import Contract, ContractDetails
except Exception:  # pragma: no cover - tests without ibapi
    Contract = None  # type: ignore[assignment]
    ContractDetails = Any  # type: ignore[assignment]

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


_TICK_TYPE_NAMES: dict[int, str] = {}
for _name in ("LAST", "DELAYED_LAST", "MARK_PRICE", "CLOSE", "DELAYED_CLOSE"):
    _value = getattr(TickTypeEnum, _name, None)
    if isinstance(_value, int):
        _TICK_TYPE_NAMES[int(_value)] = _name


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

_VIX_CACHE: dict[str, Any] = {}
_CONTRACT_DETAILS_CACHE: dict[str, Any] = {}
_CONTRACT_DETAILS_LOCK = threading.Lock()

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


def _tick_type_name(tick_type: int) -> str:
    return _TICK_TYPE_NAMES.get(int(tick_type), str(tick_type))


def _parse_ibkr_exchange(raw_exchange: str) -> tuple[str, Optional[str]]:
    parts = raw_exchange.split("@", 1)
    exchange = parts[0].strip().upper()
    primary = parts[1].strip().upper() if len(parts) == 2 else None
    return exchange, primary if primary else None


def _contract_cache_key(exchange: str, primary: Optional[str]) -> str:
    return f"{exchange.upper()}@{primary or ''}"


def _build_vix_contract(exchange: str, primary: Optional[str]) -> Any:
    if Contract is None:
        return None
    try:
        contract = Contract()
    except Exception as exc:  # pragma: no cover - contract creation issues
        logger.warning(f"Failed to construct VIX contract for {exchange}: {exc}")
        return None
    contract.symbol = "VIX"
    contract.secType = "IND"
    contract.currency = "USD"
    contract.exchange = exchange
    return contract


def _cache_contract_details(key: str, details: Any) -> None:
    with _CONTRACT_DETAILS_LOCK:
        _CONTRACT_DETAILS_CACHE[key] = details


def _cached_contract_details(key: str) -> Any:
    with _CONTRACT_DETAILS_LOCK:
        return _CONTRACT_DETAILS_CACHE.get(key)


def _memory_cache_ttl() -> float:
    try:
        ttl = float(cfg_get("VIX_MEMORY_TTL_SECONDS", 0))
    except (TypeError, ValueError):
        ttl = 0.0
    return max(0.0, min(ttl, 60.0))


def is_rth_open(details: ContractDetails, now_utc: datetime) -> bool:
    trading_hours = getattr(details, "tradingHours", "") or ""
    tz_name = getattr(details, "timeZoneId", "") or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc

    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    local_now = now_utc.astimezone(tz)
    target_day = local_now.strftime("%Y%m%d")

    pattern = re.compile(r"(\d{8}:)")
    matches = list(pattern.finditer(trading_hours))
    segments: list[str] = []
    if matches:
        for idx, match in enumerate(matches):
            start = match.start()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(trading_hours)
            segment = trading_hours[start:end].strip(" ,;")
            if segment:
                segments.append(segment)
    elif trading_hours.strip():
        segments.append(trading_hours.strip())

    for segment in segments:
        if ":" not in segment:
            continue
        day, hours = segment.split(":", 1)
        day = day.strip()
        if day != target_day:
            continue
        hours = hours.strip()
        if not hours or hours.upper() == "CLOSED":
            return False
        windows = [part.strip() for part in hours.split(",") if part.strip()]
        matched_window = False
        try:
            day_date = datetime.strptime(day, "%Y%m%d").date()
        except ValueError:
            return False
        for window in windows:
            if window.upper() == "CLOSED" or "-" not in window:
                continue
            start_str, end_str = window.split("-", 1)
            try:
                start_time = dtime(int(start_str[:2]), int(start_str[2:4]))
                end_time = dtime(int(end_str[:2]), int(end_str[2:4]))
            except (ValueError, TypeError):
                continue
            matched_window = True
            start_dt = datetime.combine(day_date, start_time, tzinfo=tz)
            end_dt = datetime.combine(day_date, end_time, tzinfo=tz)
            if end_dt <= start_dt:
                end_dt += timedelta(days=1)
            if start_dt <= local_now < end_dt:
                return True
        return False if matched_window else False
    return False


def select_tick(
    ticks: Dict[int, float], *, rth_open: bool, mode: str = "last_known"
) -> Optional[tuple[int, float]]:
    if mode != "last_known":
        return None

    def _pick(candidates: tuple[Optional[int], ...]) -> Optional[tuple[int, float]]:
        for tick_type in candidates:
            if not isinstance(tick_type, int):
                continue
            value = ticks.get(tick_type)
            if value is None:
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(number) or number <= 0:
                continue
            return tick_type, float(number)
        return None

    last_candidates = (
        getattr(TickTypeEnum, "LAST", None),
        getattr(TickTypeEnum, "DELAYED_LAST", None),
    )
    mark_candidates = (getattr(TickTypeEnum, "MARK_PRICE", None),)
    close_candidates = (
        getattr(TickTypeEnum, "CLOSE", None),
        getattr(TickTypeEnum, "DELAYED_CLOSE", None),
    )

    if rth_open:
        selection = _pick(last_candidates)
        if selection:
            return selection
        selection = _pick(mark_candidates)
        if selection:
            return selection
        return _pick(close_candidates)

    return _pick(close_candidates)

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




def _format_ib_source(exchange: str, tick_type: int, md_type: int, *, include_tick: bool) -> str:
    exchange_label = exchange.upper() if exchange else "IBKR"
    base = f"ibkr:{exchange_label}" if exchange else "ibkr"
    if include_tick:
        return f"{base}|{_tick_type_name(tick_type)}|md={md_type}"
    return base


def _iter_exchanges(settings: VixConfig) -> list[str]:
    raw = cfg_get("VIX_EXCHANGES", None)
    if isinstance(raw, str):
        items = [part.strip() for part in raw.split(",") if part.strip()]
    elif isinstance(raw, (list, tuple)):
        items = [str(part).strip() for part in raw if str(part).strip()]
    else:
        items = []
    if not items:
        items = settings.ib_exchanges or ["CBOE", "CBOEIND"]

    seen: set[str] = set()
    unique_items: list[str] = []
    for item in items:
        key = item.upper()
        if key in seen:
            continue
        seen.add(key)
        unique_items.append(item)

    enumerated = list(enumerate(unique_items))

    def _priority(entry: tuple[int, str]) -> tuple[int, int]:
        _, value = entry
        exchange, primary = _parse_ibkr_exchange(value)
        if exchange == "CBOE" and primary is None:
            tier = 0
        elif exchange == "CBOE":
            tier = 1
        else:
            tier = 2
        return tier, entry[0]

    enumerated.sort(key=_priority)
    return [value for _, value in enumerated]


def _is_invalid_exchange_error(message: str) -> bool:
    lowered = message.lower()
    return "error 200" in lowered and "ib error" in lowered


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

    policy = str(cfg_get("VIX_PRICE_POLICY", "last_known") or "last_known").lower()
    include_tick = bool(cfg_get("VIX_LOG_TICK_SOURCE", True))
    rth_timeout_ms = int(cfg_get("VIX_RTH_TIMEOUT_MS", 1500))
    off_timeout_ms = int(cfg_get("VIX_OFFHOURS_TIMEOUT_MS", 1500))
    contract_details_timeout_ms = int(
        max(500, float(cfg_get("CONTRACT_DETAILS_TIMEOUT", 2)) * 1000)
    )

    logger.debug(
        "Connecting to IBKR for VIX host=%s port=%s client_id=%s timeout=%ss",
        host,
        port,
        client_id,
        timeout,
    )

    try:
        app = connect_ib(
            client_id=client_id,
            host=host,
            port=port,
            timeout=int(max(1, round(timeout))),
            unique=True,
        )
    except Exception as exc:  # pragma: no cover - network failures
        logger.warning(f"IBKR VIX connection failed: {exc}")
        return None, None, str(exc)

    now_utc = datetime.now(timezone.utc)
    exchanges = _iter_exchanges(settings)
    last_error: Optional[str] = None
    try:
        for raw_exchange in exchanges:
            exchange, primary = _parse_ibkr_exchange(str(raw_exchange))
            contract = _build_vix_contract(exchange, primary)
            if contract is None:
                last_error = f"failed to build contract for {exchange}"
                continue

            cache_key = _contract_cache_key(exchange, primary)
            details = _cached_contract_details(cache_key)
            if details is None:
                try:
                    details = app.get_contract_details(
                        contract, timeout_ms=contract_details_timeout_ms
                    )
                except TimeoutError:
                    logger.warning(
                        "IBKR contract details timeout for %s (timeout_ms=%s)",
                        exchange,
                        contract_details_timeout_ms,
                    )
                    details = None
                except Exception as exc:  # pragma: no cover - defensive logging
                    message = str(exc)
                    logger.warning(
                        "IBKR contract details failed for %s: %s", exchange, message
                    )
                    if _is_invalid_exchange_error(message):
                        last_error = message
                        continue
                    details = None
                else:
                    if details is not None:
                        _cache_contract_details(cache_key, details)

            rth_open = False
            if details is not None:
                try:
                    rth_open = is_rth_open(details, now_utc)
                except Exception as exc:  # pragma: no cover - unexpected parsing
                    logger.warning(
                        "Failed to parse trading hours for %s: %s", exchange, exc
                    )

            md_sequence = [1, 2, 3] if rth_open else [2, 4]
            timeout_ms = rth_timeout_ms if rth_open else off_timeout_ms
            invalid_exchange = False
            for md_type in md_sequence:
                try:
                    ticks = app.request_snapshot_with_mdtype(
                        contract, md_type, timeout_ms=timeout_ms
                    )
                except TimeoutError:
                    logger.debug(
                        "IBKR snapshot timeout exchange=%s mdType=%s timeout_ms=%s",
                        exchange,
                        md_type,
                        timeout_ms,
                    )
                    last_error = "timeout"
                    continue
                except Exception as exc:  # pragma: no cover - network failures
                    message = str(exc)
                    logger.debug(
                        "IBKR snapshot error exchange=%s mdType=%s: %s",
                        exchange,
                        md_type,
                        message,
                    )
                    if _is_invalid_exchange_error(message):
                        last_error = message
                        invalid_exchange = True
                        break
                    last_error = message
                    continue

                selection = select_tick(ticks, rth_open=rth_open, mode=policy)
                if selection:
                    tick_type, value = selection
                    source = _format_ib_source(
                        exchange, tick_type, md_type, include_tick=include_tick
                    )
                    logger.info(
                        "VIX=%s source=%s policy=%s rth_open=%s",
                        f"{value:.4f}",
                        source,
                        policy,
                        rth_open,
                    )
                    return value, source, None

            if invalid_exchange:
                continue

            last_error = (
                f"no acceptable tick (exchange={exchange}, policy={policy}, rth_open={rth_open})"
            )

        if last_error is None:
            last_error = f"VIX fetch failed: no acceptable tick (policy={policy}, rth_open=False)"
        return None, None, last_error
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
    ttl = _memory_cache_ttl()
    if ttl <= 0:
        _VIX_CACHE.clear()
        return
    _VIX_CACHE.update({"value": value, "source": source, "ts": time.monotonic(), "ttl": ttl})


def _memory_cache_entry() -> Tuple[Optional[float], Optional[str]]:
    ttl = _memory_cache_ttl()
    if ttl <= 0 or not _VIX_CACHE:
        return None, None
    ts = _VIX_CACHE.get("ts")
    if ts is None:
        return None, None
    if time.monotonic() - float(ts) <= ttl:
        return _VIX_CACHE.get("value"), _VIX_CACHE.get("source")
    _VIX_CACHE.clear()
    return None, None


async def _get_vix_value() -> Tuple[Optional[float], Optional[str]]:
    """Return cached VIX value or fetch according to configured order."""

    cached_value, cached_source = _memory_cache_entry()
    if cached_value is not None or ("value" in _VIX_CACHE):
        return cached_value, cached_source

    settings = _vix_settings()
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
            return value, label
        if error:
            errors[source_name] = error

    logger.error(
        "Failed to retrieve VIX from any source: %s",
        "; ".join(f"{src} -> {msg}" for src, msg in errors.items()) or "no sources",
    )
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
