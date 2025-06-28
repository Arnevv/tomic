from __future__ import annotations

"""Helpers for retrieving IV data from the Polygon API."""

from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List
import time

import requests

from tomic.config import get as cfg_get
from tomic.logutils import logger
from tomic.journal.utils import load_json


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Expiry planning
# ---------------------------------------------------------------------------


class ExpiryPlanner:
    """Return upcoming third-Friday expiries."""

    @staticmethod
    def get_next_third_fridays(start: date, count: int = 4) -> List[date]:
        result: List[date] = []
        year = start.year
        month = start.month
        while len(result) < count:
            for day in range(15, 22):
                try:
                    cand = date(year, month, day)
                except ValueError:
                    continue
                if cand.weekday() == 4:  # Friday
                    if cand > start:
                        result.append(cand)
                    break
            if month == 12:
                year += 1
                month = 1
            else:
                month += 1
        return result


# ---------------------------------------------------------------------------
# Snapshot fetching
# ---------------------------------------------------------------------------


class SnapshotFetcher:
    """Retrieve option snapshot data from Polygon."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def fetch_expiry(self, symbol: str, expiry: str) -> List[Dict[str, Any]]:
        url = f"https://api.polygon.io/v3/snapshot/options/{symbol.upper()}"
        params = {"expiration_date": expiry, "apiKey": self.api_key}
        options: List[Dict[str, Any]] = []
        next_url: str | None = url
        first = True
        while next_url:
            if first:
                logger.info(f"Requesting snapshot for {symbol} {expiry}")
                time.sleep(13)
                resp = requests.get(next_url, params=params, timeout=10)
                first = False
            else:
                resp = requests.get(
                    next_url, params={"apiKey": self.api_key}, timeout=10
                )
            status = getattr(resp, "status_code", "n/a")
            text = getattr(resp, "text", "")
            logger.debug(f"Response {status}: {text[:200]}")
            try:
                resp.raise_for_status()
                payload = resp.json()
            except Exception as exc:  # pragma: no cover - network failure
                logger.warning(f"Polygon request failed for {symbol}: {exc}")
                break
            results = payload.get("results", {})
            if isinstance(results, dict):
                opts = results.get("options") or []
            elif isinstance(results, list):  # pragma: no cover - alt structure
                opts = results
            else:
                opts = []
            if isinstance(opts, list):
                options.extend(opts)
            next_url = payload.get("next_url")
            if next_url and not next_url.startswith("http"):
                next_url = f"https://api.polygon.io{next_url}"
            if next_url:
                time.sleep(0.2)
        logger.info(f"{symbol} {expiry}: {len(options)} contracts")
        return options


# ---------------------------------------------------------------------------
# IV extraction
# ---------------------------------------------------------------------------


class IVExtractor:
    """Extract ATM and skew information from option lists."""

    @staticmethod
    def extract_skew(
        options: List[Dict[str, Any]], spot: float
    ) -> tuple[float | None, float | None, float | None]:
        options.sort(key=lambda o: float(o.get("strike_price") or o.get("strike") or 0))
        if options:
            logger.debug(f"Voorbeeldoptie: {options[0]}")
        atm_iv: float | None = None
        atm_err = float("inf")
        call_iv: float | None = None
        put_iv: float | None = None
        for opt in options:
            right = (
                opt.get("option_type")
                or opt.get("type")
                or opt.get("contract_type")
                or opt.get("details", {}).get("contract_type")
                or opt.get("right")
            )
            strike = (
                opt.get("strike_price")
                or opt.get("strike")
                or opt.get("exercise_price")
            )
            greeks = opt.get("greeks", {})
            iv = (
                opt.get("implied_volatility")
                or opt.get("iv")
                or greeks.get("iv")
            )
            delta = opt.get("delta") or greeks.get("delta")
            if None in (right, strike, iv) or delta is None:
                continue
            try:
                strike_f = float(strike)
                iv_f = float(iv)
                delta_f = float(delta)
            except Exception:
                continue
            diff = abs(strike_f - spot)
            if diff < atm_err and str(right).lower().startswith("c"):
                logger.debug(
                    f"ATM-candidate: strike={strike_f}, iv={iv_f}, spot={spot}"
                )
                atm_err = diff
                atm_iv = iv_f
            if (
                str(right).lower().startswith("c")
                and call_iv is None
                and delta_f <= 0.25
            ):
                logger.debug(
                    f"call-option: strike={strike_f}, delta={delta_f}, iv={iv_f}"
                )
                call_iv = iv_f
            if (
                str(right).lower().startswith("p")
                and put_iv is None
                and -delta_f <= 0.25
            ):
                logger.debug(
                    f"put-option: strike={strike_f}, delta={delta_f}, iv={iv_f}"
                )
                put_iv = iv_f
            if call_iv is not None and put_iv is not None:
                break
        return atm_iv, call_iv, put_iv

    @staticmethod
    def extract_atm_call(options: List[Dict[str, Any]], spot: float) -> float | None:
        atm_iv: float | None = None
        atm_err = float("inf")
        for opt in options:
            right = (
                opt.get("option_type")
                or opt.get("type")
                or opt.get("contract_type")
                or opt.get("details", {}).get("contract_type")
                or opt.get("right")
            )
            if not right or not str(right).lower().startswith("c"):
                continue
            strike = (
                opt.get("strike_price")
                or opt.get("strike")
                or opt.get("exercise_price")
            )
            greeks = opt.get("greeks", {})
            iv = opt.get("implied_volatility") or opt.get("iv") or greeks.get("iv")
            if strike is None or iv is None:
                continue
            try:
                strike_f = float(strike)
                iv_f = float(iv)
            except Exception:
                continue
            diff = abs(strike_f - spot)
            if diff < atm_err:
                atm_err = diff
                atm_iv = iv_f
        return atm_iv


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_polygon_iv30d(symbol: str) -> Dict[str, float | None]:
    """Return volatility metrics for ``symbol`` using filtered snapshots."""
    spot, spot_date = _load_latest_close(symbol)
    if spot is None or spot_date is None:
        logger.warning(f"No price history for {symbol}")
        return {"atm_iv": None, "skew": None, "term_m1_m2": None, "term_m1_m3": None}

    api_key = cfg_get("POLYGON_API_KEY", "")
    today_dt = datetime.strptime(spot_date, "%Y-%m-%d").date()
    expiries = ExpiryPlanner.get_next_third_fridays(today_dt, count=4)

    target: date | None = None
    for exp in expiries:
        dte = (exp - today_dt).days
        if 15 <= dte <= 45:
            target = exp
            break
    if target is None:
        logger.warning(f"No suitable expiry found for {symbol}")
        return {"atm_iv": None, "skew": None, "term_m1_m2": None, "term_m1_m3": None}

    idx = expiries.index(target)
    month2 = expiries[idx + 1] if idx + 1 < len(expiries) else None
    month3 = expiries[idx + 2] if idx + 2 < len(expiries) else None

    fetcher = SnapshotFetcher(api_key)
    opts1 = fetcher.fetch_expiry(symbol, target.strftime("%Y-%m-%d"))
    atm_iv, call_iv, put_iv = IVExtractor.extract_skew(opts1, spot)

    iv_month2 = iv_month3 = None
    if month2:
        opts2 = fetcher.fetch_expiry(symbol, month2.strftime("%Y-%m-%d"))
        iv_month2 = IVExtractor.extract_atm_call(opts2, spot)
    if month3:
        opts3 = fetcher.fetch_expiry(symbol, month3.strftime("%Y-%m-%d"))
        iv_month3 = IVExtractor.extract_atm_call(opts3, spot)

    term_m1_m2 = None
    term_m1_m3 = None
    if atm_iv is not None and iv_month2 is not None:
        term_m1_m2 = round((atm_iv - iv_month2) * 100, 2)
    if atm_iv is not None and iv_month3 is not None:
        term_m1_m3 = round((atm_iv - iv_month3) * 100, 2)

    skew = None
    if call_iv is not None and put_iv is not None:
        skew = round((put_iv - call_iv) * 100, 2)

    return {
        "atm_iv": atm_iv,
        "skew": skew,
        "term_m1_m2": term_m1_m2,
        "term_m1_m3": term_m1_m3,
    }


__all__ = ["fetch_polygon_iv30d"]
