from __future__ import annotations

"""Helpers for retrieving IV data from the Polygon API."""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import requests

from tomic.config import get as cfg_get
from tomic.logutils import logger
from tomic.journal.utils import load_json


def _load_latest_close(symbol: str) -> tuple[float | None, str | None]:
    """Return the most recent close and its date for ``symbol``."""
    base = Path(cfg_get("PRICE_HISTORY_DIR", "tomic/data/spot_prices"))
    path = base / f"{symbol}.json"
    logger.debug(f"Loading close price for {symbol} from {path}")
    data = load_json(path)
    if isinstance(data, list) and data:
        data.sort(key=lambda r: r.get("date", ""))
        rec = data[-1]
        try:
            price = float(rec.get("close"))
            date_str = str(rec.get("date"))
            logger.debug(f"Using last close for {symbol} on {date_str}: {price}")
            return price, date_str
        except Exception:
            return None, None
    return None, None


def fetch_polygon_iv30d(symbol: str) -> float | None:
    """Return approximate 30-day IV for ``symbol`` using the Polygon snapshot."""
    spot, spot_date = _load_latest_close(symbol)
    if spot is None or spot_date is None:
        logger.warning(f"No price history for {symbol}")
        return None

    api_key = cfg_get("POLYGON_API_KEY", "")
    url = f"https://api.polygon.io/v3/snapshot/options/{symbol.upper()}"
    try:
        logger.debug(f"Requesting {url} with apiKey={api_key}")
        resp = requests.get(url, params={"apiKey": api_key}, timeout=10)
        status = getattr(resp, "status_code", "n/a")
        text = getattr(resp, "text", "")
        logger.debug(f"Response {status}: {text[:200]}")
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:  # pragma: no cover - network failure
        logger.warning(f"Polygon request failed for {symbol}: {exc}")
        return None

    results = payload.get("results", {})
    if isinstance(results, dict):
        options: List[Dict[str, Any]] = results.get("options") or []
    elif isinstance(results, list):  # pragma: no cover - alt structure
        options = results
    else:
        options = []

    if not options:
        logger.warning(f"No option data for {symbol}")
        return None

    today_dt = datetime.strptime(spot_date, "%Y-%m-%d").date()
    ivs: List[float] = []
    for opt in options:
        exp_raw = opt.get("expiration_date") or opt.get("expDate")
        strike = (
            opt.get("strike_price")
            or opt.get("strike")
            or opt.get("exercise_price")
        )
        iv = opt.get("implied_volatility") or opt.get("iv")
        if exp_raw is None or strike is None or iv is None:
            continue
        try:
            if "-" in str(exp_raw):
                exp_dt = datetime.strptime(str(exp_raw), "%Y-%m-%d").date()
            else:
                exp_dt = datetime.strptime(str(exp_raw), "%Y%m%d").date()
            dte = (exp_dt - today_dt).days
            if dte < 25 or dte > 35:
                continue
            if abs(float(strike) - spot) > 1:
                continue
            ivs.append(float(iv))
        except Exception:
            continue

    logger.debug(f"{symbol}: {len(ivs)} contracts after filtering")
    if not ivs:
        logger.warning(f"No valid IV records for {symbol}")
        return None
    return sum(ivs) / len(ivs)

__all__ = ["fetch_polygon_iv30d"]
