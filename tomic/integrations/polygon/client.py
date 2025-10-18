from __future__ import annotations

"""Polygon REST API client implementing :class:`MarketDataProvider`."""

import os
import random
import time
from typing import Any, Dict, List

import requests

from ... import config as cfg
from ...logutils import logger
from ...market_provider import MarketDataProvider

# Enable full API key logging when TOMIC_SHOW_POLYGON_KEY is truthy
_SHOW_POLYGON_KEY = os.getenv("TOMIC_SHOW_POLYGON_KEY", "0").lower() not in {
    "0",
    "",
    "false",
    "no",
}


class PolygonClient(MarketDataProvider):
    """Simple wrapper around Polygon's REST API."""

    BASE_URL = "https://api.polygon.io"

    def __init__(self, api_key: str | None = None) -> None:
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
        params = dict(params or {})
        api_key = self._next_api_key()
        if api_key:
            display_key = api_key if _SHOW_POLYGON_KEY else f"{api_key[:5]}***"
            logger.debug(f"Using Polygon key: {display_key}")
        url = f"{self.BASE_URL.rstrip('/')}/{path.lstrip('/')}"
        attempts = 0
        key_attempts = 0
        max_keys = max(len(self._api_keys), 1)

        while True:
            params["apiKey"] = api_key
            masked_key = api_key if _SHOW_POLYGON_KEY else "***"
            masked = {**params, "apiKey": masked_key}
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
                    break
                continue

            if status == 403 and key_attempts < max_keys - 1:
                key_attempts += 1
                display_key = api_key if _SHOW_POLYGON_KEY else f"{api_key[:5]}***"
                logger.warning(
                    f"Polygon 403 for key {display_key} — trying next key."
                )
                api_key = self._next_api_key()
                if api_key:
                    display_key = (
                        api_key if _SHOW_POLYGON_KEY else f"{api_key[:5]}***"
                    )
                    logger.debug(f"Using Polygon key: {display_key}")
                continue

            break

        resp.raise_for_status()
        try:
            return resp.json()
        except Exception as exc:  # pragma: no cover - invalid JSON
            logger.warning(f"Invalid JSON from Polygon for {path}: {exc}")
            return {}

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
