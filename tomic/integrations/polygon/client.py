from __future__ import annotations

"""Polygon REST API client implementing :class:`MarketDataProvider`."""

import random
import threading
import time
from enum import Enum
from typing import Any, Dict, List

import requests

from ... import config as cfg
from ...logutils import logger
from ...market_provider import MarketDataProvider


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation, requests allowed
    OPEN = "open"  # Circuit tripped, requests blocked
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open and blocking requests."""

    pass


class CircuitBreaker:
    """Circuit breaker pattern implementation for API resilience.

    Tracks failures and temporarily blocks requests when a service is unhealthy,
    preventing cascade failures and allowing the service time to recover.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 3,
    ) -> None:
        """Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before trying half-open state
            half_open_max_calls: Max calls allowed in half-open state
        """
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._half_open_max_calls = half_open_max_calls

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float | None = None
        self._half_open_calls = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        """Return current circuit state, transitioning if needed."""
        with self._lock:
            if self._state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
                    logger.info("Circuit breaker transitioning to HALF_OPEN")
            return self._state

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt recovery."""
        if self._last_failure_time is None:
            return True
        return (time.monotonic() - self._last_failure_time) >= self._recovery_timeout

    def allow_request(self) -> bool:
        """Check if a request should be allowed through."""
        current_state = self.state
        if current_state == CircuitState.CLOSED:
            return True
        if current_state == CircuitState.OPEN:
            return False
        # HALF_OPEN: allow limited requests
        with self._lock:
            if self._half_open_calls < self._half_open_max_calls:
                self._half_open_calls += 1
                return True
            return False

    def record_success(self) -> None:
        """Record a successful request."""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._half_open_calls = 0
                logger.info("Circuit breaker CLOSED after successful request")
            elif self._state == CircuitState.CLOSED:
                # Gradual recovery: reduce failure count on success
                self._failure_count = max(0, self._failure_count - 1)

    def record_failure(self) -> None:
        """Record a failed request."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                logger.warning("Circuit breaker OPEN after half-open failure")
            elif (
                self._state == CircuitState.CLOSED
                and self._failure_count >= self._failure_threshold
            ):
                self._state = CircuitState.OPEN
                logger.warning(
                    f"Circuit breaker OPEN after {self._failure_count} failures"
                )

    def reset(self) -> None:
        """Manually reset the circuit breaker."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._last_failure_time = None
            self._half_open_calls = 0
            logger.info("Circuit breaker manually reset")


# API key index for logging purposes (never log actual keys)
def _mask_key_index(idx: int, total: int) -> str:
    """Return a safe identifier for API key logging without exposing key content."""
    return f"key_{idx + 1}_of_{total}" if total > 1 else "***"


class PolygonClient(MarketDataProvider):
    """Simple wrapper around Polygon's REST API."""

    BASE_URL = "https://api.polygon.io"

    def __init__(
        self,
        api_key: str | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        keys = (
            api_key
            or cfg.get("POLYGON_API_KEYS")
            or cfg.get("POLYGON_API_KEY", "")
        )
        if isinstance(keys, str):
            keys = [k.strip() for k in keys.split(",") if k.strip()]
        self._api_keys: List[str] = list(keys) if keys else []
        self._api_idx = 0
        self._session: requests.Session | None = None
        # Circuit breaker for API resilience - prevents cascade failures
        self._circuit_breaker = circuit_breaker or CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60.0,
            half_open_max_calls=3,
        )

    def _next_api_key(self) -> str:
        if not self._api_keys:
            return ""
        key = self._api_keys[self._api_idx % len(self._api_keys)]
        self._api_idx += 1
        return key

    def connect(self) -> None:
        self._session = requests.Session()

    def disconnect(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None

    # Internal helper -------------------------------------------------
    def _request(self, path: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
        if self._session is None:
            raise RuntimeError("Client not connected")

        # Check circuit breaker before making request
        if not self._circuit_breaker.allow_request():
            logger.warning(
                f"Circuit breaker OPEN - blocking request to {path}. "
                f"Service may be unavailable."
            )
            raise CircuitBreakerError(
                f"Polygon API circuit breaker is open. Request to {path} blocked."
            )

        params = dict(params or {})
        api_key = self._next_api_key()
        total_keys = len(self._api_keys)
        current_key_idx = (self._api_idx - 1) % max(total_keys, 1)
        if api_key:
            logger.debug(f"Using Polygon {_mask_key_index(current_key_idx, total_keys)}")
        url = f"{self.BASE_URL.rstrip('/')}/{path.lstrip('/')}"
        attempts = 0
        key_attempts = 0
        max_keys = max(total_keys, 1)

        try:
            while True:
                params["apiKey"] = api_key
                masked = {**params, "apiKey": "***"}
                logger.debug(f"GET {url} params={masked}")
                resp = self._session.get(url, params=params, timeout=10)
                status = getattr(resp, "status_code", "n/a")
                text = getattr(resp, "text", "")
                logger.debug(f"Response {status}: {text[:200]}")

                if status == 429:
                    attempts += 1
                    wait = min(60, 2 ** attempts + random.uniform(0, 1))
                    logger.warning(
                        f"Polygon rate limit hit (attempt {attempts}), sleeping {wait:.1f}s"
                    )
                    time.sleep(wait)
                    if attempts >= 5:
                        # Record failure for circuit breaker after max retries
                        self._circuit_breaker.record_failure()
                        break
                    continue

                if status == 403 and key_attempts < max_keys - 1:
                    key_attempts += 1
                    failed_key_id = _mask_key_index(current_key_idx, total_keys)
                    logger.warning(
                        f"Polygon 403 for {failed_key_id} — trying next key."
                    )
                    api_key = self._next_api_key()
                    current_key_idx = (self._api_idx - 1) % max(total_keys, 1)
                    if api_key:
                        logger.debug(f"Using Polygon {_mask_key_index(current_key_idx, total_keys)}")
                    continue

                # Check for server errors (5xx) - these should trip the circuit
                if isinstance(status, int) and 500 <= status < 600:
                    self._circuit_breaker.record_failure()
                    resp.raise_for_status()

                break

            resp.raise_for_status()
            # Record success for circuit breaker
            self._circuit_breaker.record_success()
            try:
                return resp.json()
            except ValueError as exc:  # JSON decode error
                logger.warning(f"Invalid JSON from Polygon for {path}: {exc}")
                return {}

        except requests.exceptions.Timeout as exc:
            self._circuit_breaker.record_failure()
            logger.error(f"Polygon request timeout for {path}: {exc}")
            raise
        except requests.exceptions.ConnectionError as exc:
            self._circuit_breaker.record_failure()
            logger.error(f"Polygon connection error for {path}: {exc}")
            raise
        except requests.exceptions.HTTPError as exc:
            # 4xx errors (except 429) don't trip the circuit - they're client errors
            status_code = getattr(exc.response, "status_code", 0)
            if isinstance(status_code, int) and status_code >= 500:
                self._circuit_breaker.record_failure()
            raise

    # MarketDataProvider API -----------------------------------------
    def fetch_option_chain(self, symbol: str) -> List[Dict[str, Any]]:
        """Return option contracts for ``symbol`` using Polygon."""
        data = self._request(
            "v3/reference/options/contracts",
            {"underlying_ticker": symbol.upper()},
        )
        return data.get("results", [])

    def fetch_market_metrics(self, symbol: str) -> Dict[str, Any]:
        """Return simple market metrics for ``symbol`` from Polygon."""
        data = self._request(f"v2/aggs/ticker/{symbol.upper()}/prev", {})
        results = data.get("results") or []
        spot = results[0].get("c") if results else None
        return {"spot_price": spot}

    def fetch_spot_price(self, symbol: str) -> float | None:
        """Return the latest trade price for ``symbol``."""
        # Probeer eerst de snapshot-endpoint
        data = self._request(
            f"v2/snapshot/locale/us/markets/stocks/tickers/{symbol.upper()}"
        )
        ticker = data.get("ticker") or {}
        price = None
        last_trade = ticker.get("lastTrade") or ticker.get("last") or {}
        if last_trade:
            price = last_trade.get("p") or last_trade.get("price")
        if price is None:
            price = ticker.get("day", {}).get("c") or ticker.get("min", {}).get("c")

        # Valt terug op de last-trade-endpoint wanneer snapshot niets oplevert
        if price is None:
            data = self._request(f"v2/last/trade/{symbol.upper()}")
            result = data.get("results") or data.get("last") or {}
            price = result.get("p") or result.get("price")

        try:
            return float(price) if price is not None else None
        except Exception:
            return None

    def fetch_ticker_details(self, symbol: str) -> Dict[str, Any]:
        """Fetch ticker details including sector and industry information.

        Args:
            symbol: Stock ticker symbol.

        Returns:
            Dictionary with ticker details including:
            - name: Company name
            - market: Market type (stocks, otc, etc.)
            - locale: Market locale
            - primary_exchange: Primary exchange
            - type: Security type
            - sic_code: SIC industry code
            - sic_description: SIC industry description
            - market_cap: Market capitalization
        """
        try:
            data = self._request(f"v3/reference/tickers/{symbol.upper()}")
            results = data.get("results", {})

            return {
                "symbol": symbol.upper(),
                "name": results.get("name"),
                "market": results.get("market"),
                "locale": results.get("locale"),
                "primary_exchange": results.get("primary_exchange"),
                "type": results.get("type"),
                "sic_code": results.get("sic_code"),
                "sic_description": results.get("sic_description"),
                "market_cap": results.get("market_cap"),
                "currency": results.get("currency_name"),
            }
        except Exception as exc:
            logger.warning(f"Failed to fetch ticker details for {symbol}: {exc}")
            return {"symbol": symbol.upper()}

    def fetch_ticker_details_batch(
        self, symbols: List[str]
    ) -> Dict[str, Dict[str, Any]]:
        """Fetch ticker details for multiple symbols.

        Args:
            symbols: List of stock ticker symbols.

        Returns:
            Dictionary mapping symbol to ticker details.
        """
        results = {}
        sleep_time = cfg.get("POLYGON_SLEEP_BETWEEN", 1.2)

        for i, symbol in enumerate(symbols):
            results[symbol.upper()] = self.fetch_ticker_details(symbol)
            # Rate limiting between requests
            if i < len(symbols) - 1:
                time.sleep(sleep_time)

        return results
