"""EODHD API client for fetching earnings calendar data."""

from __future__ import annotations

import os
import time
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import requests

from ...logutils import logger


class EODHDClient:
    """Client for EODHD Calendar API - earnings dates.

    API Documentation: https://eodhd.com/financial-apis/calendar-upcoming-earnings-ipos-and-splits

    Usage:
        client = EODHDClient(api_key="your_key")
        client.connect()
        earnings = client.fetch_earnings(symbols=["AAPL", "MSFT"], from_date="2018-01-01")
        client.disconnect()
    """

    BASE_URL = "https://eodhd.com/api"

    def __init__(self, api_key: str | None = None) -> None:
        """Initialize EODHD client.

        Args:
            api_key: EODHD API key. If not provided, reads from EODHD_API_KEY env var.
        """
        self._api_key = api_key or os.getenv("EODHD_API_KEY", "")
        self._session: requests.Session | None = None

    def connect(self) -> None:
        """Open HTTP session."""
        self._session = requests.Session()

    def disconnect(self) -> None:
        """Close HTTP session."""
        if self._session is not None:
            self._session.close()
            self._session = None

    def _request(
        self,
        endpoint: str,
        params: Dict[str, Any] | None = None,
        max_retries: int = 3,
    ) -> Dict[str, Any] | List[Dict[str, Any]]:
        """Make API request with retry logic.

        Args:
            endpoint: API endpoint path (e.g., "calendar/earnings")
            params: Query parameters
            max_retries: Number of retry attempts for rate limiting

        Returns:
            JSON response as dict or list
        """
        if self._session is None:
            raise RuntimeError("Client not connected. Call connect() first.")

        if not self._api_key:
            raise ValueError("EODHD API key not configured. Set EODHD_API_KEY env var.")

        params = dict(params or {})
        params["api_token"] = self._api_key
        params["fmt"] = "json"

        url = f"{self.BASE_URL}/{endpoint}"

        for attempt in range(max_retries + 1):
            logger.debug(f"EODHD request: {endpoint} params={_mask_params(params)}")

            try:
                resp = self._session.get(url, params=params, timeout=30)
            except requests.RequestException as e:
                logger.warning(f"EODHD request failed: {e}")
                if attempt < max_retries:
                    wait = 2 ** (attempt + 1)
                    logger.info(f"Retrying in {wait}s...")
                    time.sleep(wait)
                    continue
                raise

            if resp.status_code == 429:
                wait = min(60, 2 ** (attempt + 1))
                logger.warning(f"EODHD rate limit, waiting {wait}s (attempt {attempt + 1})")
                time.sleep(wait)
                continue

            resp.raise_for_status()
            return resp.json()

        raise RuntimeError("Max retries exceeded for EODHD API")

    def fetch_earnings(
        self,
        symbols: List[str] | None = None,
        from_date: str | date | None = None,
        to_date: str | date | None = None,
    ) -> List[Dict[str, Any]]:
        """Fetch earnings calendar data.

        Args:
            symbols: List of symbols (e.g., ["AAPL", "MSFT"]). Will be formatted as "AAPL.US".
            from_date: Start date for earnings lookup (YYYY-MM-DD or date object)
            to_date: End date for earnings lookup (YYYY-MM-DD or date object)

        Returns:
            List of earnings records with fields:
            - code: Symbol with exchange (e.g., "AAPL.US")
            - report_date: Date when earnings are reported
            - date: Fiscal period end date
            - before_after_market: "BeforeMarket" or "AfterMarket"
            - actual: Actual EPS (if available)
            - estimate: Estimated EPS (if available)
        """
        params: Dict[str, Any] = {}

        if symbols:
            # EODHD expects symbols in format "AAPL.US,MSFT.US"
            formatted = [f"{s.upper()}.US" for s in symbols]
            params["symbols"] = ",".join(formatted)

        if from_date:
            params["from"] = _format_date(from_date)

        if to_date:
            params["to"] = _format_date(to_date)

        response = self._request("calendar/earnings", params)

        # Response format: {"type": "Earnings", "earnings": [...]}
        if isinstance(response, dict):
            return response.get("earnings", [])
        return response

    def fetch_earnings_by_symbol(
        self,
        symbol: str,
        from_date: str | date | None = "2018-01-01",
        to_date: str | date | None = None,
    ) -> List[Dict[str, Any]]:
        """Fetch all earnings for a single symbol.

        Convenience method that fetches historical + future earnings for one symbol.

        Args:
            symbol: Stock symbol (e.g., "AAPL")
            from_date: Start date (default: 2018-01-01 for full history)
            to_date: End date (default: None = today + future)

        Returns:
            List of earnings records sorted by report_date
        """
        return self.fetch_earnings(
            symbols=[symbol],
            from_date=from_date,
            to_date=to_date,
        )

    def fetch_all_symbols_earnings(
        self,
        symbols: List[str],
        from_date: str | date | None = "2018-01-01",
        to_date: str | date | None = None,
        batch_size: int = 50,
        delay_between_batches: float = 0.5,
    ) -> Dict[str, List[str]]:
        """Fetch earnings for multiple symbols and return formatted dict.

        Args:
            symbols: List of symbols to fetch
            from_date: Start date for historical data
            to_date: End date (None = include future)
            batch_size: Number of symbols per API call
            delay_between_batches: Seconds to wait between batches

        Returns:
            Dict mapping symbol -> list of ISO date strings (sorted ascending)
            Format matches earnings_dates.json: {"AAPL": ["2024-01-01", ...]}
        """
        result: Dict[str, List[str]] = {}

        # Process in batches to avoid URL length limits
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            logger.info(f"Fetching earnings batch {i // batch_size + 1}: {len(batch)} symbols")

            earnings = self.fetch_earnings(
                symbols=batch,
                from_date=from_date,
                to_date=to_date,
            )

            # Group by symbol
            for record in earnings:
                code = record.get("code", "")
                # Extract symbol from "AAPL.US" format
                symbol = code.split(".")[0].upper() if code else ""
                if not symbol:
                    continue

                report_date = record.get("report_date")
                if not report_date:
                    continue

                if symbol not in result:
                    result[symbol] = []

                # Avoid duplicates
                if report_date not in result[symbol]:
                    result[symbol].append(report_date)

            # Rate limiting
            if i + batch_size < len(symbols):
                time.sleep(delay_between_batches)

        # Sort dates for each symbol
        for symbol in result:
            result[symbol] = sorted(result[symbol])

        return result


def _format_date(d: str | date) -> str:
    """Convert date to YYYY-MM-DD string."""
    if isinstance(d, date):
        return d.isoformat()
    return d


def _mask_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """Mask sensitive parameters for logging."""
    masked = dict(params)
    if "api_token" in masked:
        token = masked["api_token"]
        masked["api_token"] = f"{token[:5]}***" if len(token) > 5 else "***"
    return masked
