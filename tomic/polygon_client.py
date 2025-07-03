from __future__ import annotations

"""Polygon REST API client implementing :class:`MarketDataProvider`."""

from typing import Any, Dict, List
import random
import requests
import time
from .logutils import logger

from .market_provider import MarketDataProvider
from . import config as cfg


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
        url = f"{self.BASE_URL.rstrip('/')}/{path.lstrip('/')}"
        attempts = 0
        key_attempts = 0
        max_keys = max(len(self._api_keys), 1)

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
                    break
                continue

            if status == 403 and key_attempts < max_keys - 1:
                key_attempts += 1
                api_key = self._next_api_key()
                logger.warning("Polygon unauthorized (403), rotating API key")
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
