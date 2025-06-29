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
        self.api_key = api_key or cfg.get("POLYGON_API_KEY", "")
        self._session: requests.Session | None = None

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
        params["apiKey"] = self.api_key
        masked = {**params, "apiKey": "***"}
        logger.debug(f"GET {path} params={masked}")
        attempts = 0
        while True:
            resp = self._session.get(
                f"{self.BASE_URL}/{path}", params=params, timeout=10
            )
            status = getattr(resp, "status_code", "n/a")
            text = getattr(resp, "text", "")
            logger.debug(f"Response {status}: {text[:200]}")
            if status != 429:
                break
            attempts += 1
            wait = min(60, 2 ** attempts + random.uniform(0, 1))
            logger.warning(
                f"Polygon rate limit hit (attempt {attempts}), sleeping {wait:.1f}s"
            )
            time.sleep(wait)
            if attempts >= 5:
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
