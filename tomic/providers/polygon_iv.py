from __future__ import annotations

"""Helpers for retrieving IV data from the Polygon API."""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
import time

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


def fetch_polygon_iv30d(symbol: str) -> Dict[str, float | None]:
    """Return volatility metrics for ``symbol`` using the Polygon snapshot."""
    spot, spot_date = _load_latest_close(symbol)
    if spot is None or spot_date is None:
        logger.warning(f"No price history for {symbol}")
        return {
            "atm_iv": None,
            "skew": None,
            "term_m1_m2": None,
            "term_m1_m3": None,
        }

    api_key = cfg_get("POLYGON_API_KEY", "")
    url = f"https://api.polygon.io/v3/snapshot/options/{symbol.upper()}"
    masked_key = f"***{api_key[-3:]}" if api_key else "***"
    options: List[Dict[str, Any]] = []
    next_url: str | None = url
    while next_url:
        logger.info(f"Snapshot query: {next_url}?apiKey={masked_key}")
        try:
            logger.debug(f"Requesting {next_url} with apiKey={api_key}")
            resp = requests.get(next_url, params={"apiKey": api_key}, timeout=10)
            status = getattr(resp, "status_code", "n/a")
            text = getattr(resp, "text", "")
            logger.debug(f"Response {status}: {text[:200]}")
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:  # pragma: no cover - network failure
            logger.warning(f"Polygon request failed for {symbol}: {exc}")
            break

        results = payload.get("results", {})
        if isinstance(results, dict):
            page_opts = results.get("options") or []
        elif isinstance(results, list):  # pragma: no cover - alt structure
            page_opts = results
        else:
            page_opts = []

        if isinstance(page_opts, list):
            options.extend(page_opts)

        next_url = payload.get("next_url")
        if next_url and not next_url.startswith("http"):
            next_url = f"https://api.polygon.io{next_url}"
        if next_url:
            time.sleep(0.2)

    logger.info(f"{symbol}: retrieved {len(options)} contracts total")

    if not options:
        logger.warning(f"No option data for {symbol}")
        return {
            "atm_iv": None,
            "skew": None,
            "term_m1_m2": None,
            "term_m1_m3": None,
        }

    today_dt = datetime.strptime(spot_date, "%Y-%m-%d").date()
    tolerance = max(spot * 0.03, 2.0)
    dte_filtered: List[Dict[str, Any]] = []
    valid: List[Dict[str, Any]] = []

    for opt in options:
        exp_raw = opt.get("expiration_date") or opt.get("expDate")
        strike = (
            opt.get("strike_price")
            or opt.get("strike")
            or opt.get("exercise_price")
        )
        if exp_raw is None or strike is None:
            continue

        try:
            if "-" in str(exp_raw):
                exp_dt = datetime.strptime(str(exp_raw), "%Y-%m-%d").date()
            else:
                exp_dt = datetime.strptime(str(exp_raw), "%Y%m%d").date()
            strike_f = float(strike)
        except Exception:
            continue

        dte = (exp_dt - today_dt).days
        if not 15 <= dte <= 60:
            continue
        dte_filtered.append(opt)

        iv = opt.get("implied_volatility") or opt.get("iv")
        delta = opt.get("delta") or opt.get("greeks", {}).get("delta")
        right = (
            opt.get("option_type")
            or opt.get("type")
            or opt.get("contract_type")
            or opt.get("details", {}).get("contract_type")
            or opt.get("right")
        )
        if iv is None or delta is None or right is None:
            continue

        try:
            iv_f = float(iv)
            delta_f = float(delta)
        except Exception:
            continue

        valid.append(
            {
                "expiry": exp_dt,
                "strike": strike_f,
                "iv": iv_f,
                "delta": delta_f,
                "right": str(right).lower(),
            }
        )

    logger.info(f"{symbol}: {len(dte_filtered)} contracts after DTE filter")
    logger.info(f"{symbol}: {len(valid)} contracts with valid IV")

    if not valid:
        return {
            "atm_iv": None,
            "skew": None,
            "term_m1_m2": None,
            "term_m1_m3": None,
        }

    grouped: Dict[str, List[float]] = {}
    atm_iv: float | None = None
    atm_err = float("inf")
    call_iv: float | None = None
    put_iv: float | None = None
    call_err = float("inf")
    put_err = float("inf")

    for rec in valid:
        diff = abs(rec["strike"] - spot)
        if diff < atm_err:
            atm_err = diff
            atm_iv = rec["iv"]

        if diff <= tolerance:
            grouped.setdefault(str(rec["expiry"]), []).append(rec["iv"])

        if rec["right"].startswith("c"):
            err = abs(rec["delta"] - 0.25)
            if err < call_err:
                call_err = err
                call_iv = rec["iv"]
        elif rec["right"].startswith("p"):
            err = abs(rec["delta"] + 0.25)
            if err < put_err:
                put_err = err
                put_iv = rec["iv"]

    avgs: List[float] = []
    for exp in sorted(grouped.keys()):
        ivs = grouped[exp]
        if ivs:
            avgs.append(sum(ivs) / len(ivs))

    term_m1_m2 = round((avgs[0] - avgs[1]) * 100, 2) if len(avgs) >= 2 else None
    term_m1_m3 = round((avgs[0] - avgs[2]) * 100, 2) if len(avgs) >= 3 else None

    skew = (
        round((put_iv - call_iv) * 100, 2)
        if call_iv is not None and put_iv is not None
        else None
    )

    return {
        "atm_iv": atm_iv,
        "skew": skew,
        "term_m1_m2": term_m1_m2,
        "term_m1_m3": term_m1_m3,
    }

__all__ = ["fetch_polygon_iv30d"]
