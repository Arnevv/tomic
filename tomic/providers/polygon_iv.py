from __future__ import annotations

"""Helpers for retrieving IV data from the Polygon API."""

from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List
import json
import time
import csv

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


def _export_option_chain(symbol: str, options: List[Dict[str, Any]]) -> None:
    """Write option chain to CSV using today's date and timestamp."""
    base = Path("data")
    base.mkdir(exist_ok=True)
    date_dir = base / datetime.now().strftime("%Y-%m-%d")
    date_dir.mkdir(parents=True, exist_ok=True)
    filename = (
        f"{symbol}_{datetime.now().strftime('%Y-%m-%d-%H-%M')}-optionchainpolygon.csv"
    )
    path = date_dir / filename
    headers = [
        "strike",
        "expiry",
        "right",
        "IV",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "vwap",
        "delta",
        "gamma",
        "theta",
        "vega",
    ]
    with path.open("w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(headers)
        for opt in options:
            greeks = opt.get("greeks") or {}
            day = opt.get("day") or {}
            details = opt.get("details") or {}
            writer.writerow(
                [
                    opt.get("strike_price")
                    or opt.get("strike")
                    or opt.get("exercise_price"),
                    opt.get("expiration_date")
                    or opt.get("expDate")
                    or opt.get("expiry"),
                    opt.get("option_type")
                    or opt.get("type")
                    or opt.get("contract_type")
                    or details.get("contract_type")
                    or opt.get("right"),
                    opt.get("implied_volatility")
                    or opt.get("iv")
                    or greeks.get("iv"),
                    opt.get("open") or day.get("open") or day.get("o"),
                    opt.get("high") or day.get("high") or day.get("h"),
                    opt.get("low") or day.get("low") or day.get("l"),
                    opt.get("close") or day.get("close") or day.get("c"),
                    opt.get("volume") or day.get("volume") or day.get("v"),
                    opt.get("vwap") or day.get("vwap") or day.get("vw"),
                    opt.get("delta")
                    if opt.get("delta") is not None
                    else greeks.get("delta"),
                    opt.get("gamma")
                    if opt.get("gamma") is not None
                    else greeks.get("gamma"),
                    opt.get("theta")
                    if opt.get("theta") is not None
                    else greeks.get("theta"),
                    opt.get("vega")
                    if opt.get("vega") is not None
                    else greeks.get("vega"),
                ]
            )



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
        logger.info(f"extract_skew: {len(options)} options")
        if options:
            logger.debug(f"Voorbeeldoptie: {options[0]}")
        atm_iv: float | None = None
        atm_err = float("inf")
        call_iv: float | None = None
        put_iv: float | None = None
        best_call_diff: float | None = None
        best_put_diff: float | None = None
        skipped = 0
        missing_iv = 0
        missing_delta = 0
        in_range = 0
        seen_call_delta = False
        seen_put_delta = False
        fallback_call_iv: float | None = None
        fallback_call_diff: float | None = None
        fallback_put_iv: float | None = None
        fallback_put_diff: float | None = None
        for opt in options:
            details = opt.get("details") or {}
            right = (
                opt.get("option_type")
                or opt.get("type")
                or opt.get("contract_type")
                or details.get("contract_type")
                or opt.get("right")
            )
            strike = (
                opt.get("strike_price")
                or opt.get("strike")
                or opt.get("exercise_price")
            )
            greeks = opt.get("greeks") or {}
            iv = opt.get("implied_volatility")
            if iv is None:
                iv = opt.get("iv")
            if iv is None:
                iv = greeks.get("iv")
            delta = (
                opt.get("delta")
                if opt.get("delta") is not None
                else greeks.get("delta")
            )
            logger.debug(f"Option raw greeks: {opt.get('greeks')}")
            logger.debug(f"strike={strike}, delta={delta}, iv={iv}, type={right}")
            if right is None or strike is None:
                skipped += 1
                logger.debug(
                    f"Filtered out: strike={strike}, iv={iv}, delta={delta}, right={right}"
                )
                continue

            iv_f: float | None = None
            try:
                if iv is not None:
                    iv_f = float(iv)
                else:
                    missing_iv += 1
            except Exception:
                missing_iv += 1
            if iv_f is None:
                skipped += 1
                logger.debug(
                    f"Filtered out: strike={strike}, iv={iv}, delta={delta}, right={right}"
                )
                continue
            try:
                strike_f = float(strike)
            except Exception:
                skipped += 1
                logger.debug(f"Invalid numeric data: {json.dumps(opt)}")
                continue
            diff = abs(strike_f - spot)
            if str(right).lower().startswith("c"):
                if diff < atm_err:
                    logger.debug(
                        f"ATM-candidate: strike={strike_f}, iv={iv_f}, spot={spot}"
                    )
                    atm_err = diff
                    atm_iv = iv_f
                if fallback_call_diff is None or diff < fallback_call_diff:
                    fallback_call_diff = diff
                    fallback_call_iv = iv_f
            elif str(right).lower().startswith("p"):
                if fallback_put_diff is None or diff < fallback_put_diff:
                    fallback_put_diff = diff
                    fallback_put_iv = iv_f

            delta_f: float | None = None
            if delta is not None:
                try:
                    delta_f = float(delta)
                except Exception:
                    logger.debug(f"Invalid delta: {json.dumps(opt)}")
                    delta_f = None
            if delta_f is None:
                missing_delta += 1
                continue
            else:
                if str(right).lower().startswith("c") and 0.15 <= delta_f <= 0.35:
                    in_range += 1
                if str(right).lower().startswith("c"):
                    seen_call_delta = True
                elif (
                    str(right).lower().startswith("p")
                    and 0.15 <= abs(delta_f) <= 0.35
                    and delta_f < 0
                ):
                    in_range += 1
                if str(right).lower().startswith("p"):
                    seen_put_delta = True

            if str(right).lower().startswith("c") and 0.15 <= delta_f <= 0.35:
                diff_c = abs(delta_f - 0.25)
                if best_call_diff is None or diff_c < best_call_diff:
                    logger.debug(
                        f"call-option candidate: strike={strike_f}, delta={delta_f}, iv={iv_f}"
                    )
                    best_call_diff = diff_c
                    call_iv = iv_f
            elif (
                str(right).lower().startswith("p")
                and 0.15 <= abs(delta_f) <= 0.35
                and delta_f < 0
            ):
                diff_p = abs(delta_f + 0.25)
                if best_put_diff is None or diff_p < best_put_diff:
                    logger.debug(
                        f"put-option candidate: strike={strike_f}, delta={delta_f}, iv={iv_f}"
                    )
                    best_put_diff = diff_p
                    put_iv = iv_f
        if call_iv is None and fallback_call_iv is not None and seen_call_delta:
            logger.warning("No valid delta for call; using best-effort estimate")
            call_iv = fallback_call_iv
        if put_iv is None and fallback_put_iv is not None and seen_put_delta:
            logger.warning("No valid delta for put; using best-effort estimate")
            put_iv = fallback_put_iv

        logger.warning(
            f"{len(options)} opties verwerkt, {missing_iv} zonder IV, {missing_delta} zonder delta, {in_range} binnen delta-range"
        )
        logger.info(
            f"Processed {len(options)} options, skipped {skipped}, atm_iv={atm_iv}, call_iv={call_iv}, put_iv={put_iv}"
        )
        return atm_iv, call_iv, put_iv

    @staticmethod
    def extract_atm_call(
        options: List[Dict[str, Any]], spot: float, symbol: str
    ) -> tuple[float | None, float | None]:
        iv_candidates: list[tuple[float, float, float]] = []
        for opt in options:
            details = opt.get("details") or {}
            right = (
                opt.get("option_type")
                or opt.get("type")
                or opt.get("contract_type")
                or details.get("contract_type")
                or opt.get("right")
            )
            if not right or not str(right).lower().startswith("c"):
                continue
            strike = (
                opt.get("strike_price")
                or opt.get("strike")
                or opt.get("exercise_price")
            )
            greeks = opt.get("greeks") or {}
            iv = opt.get("implied_volatility")
            if iv is None:
                iv = opt.get("iv")
            if iv is None:
                iv = greeks.get("iv")
            delta = (
                opt.get("delta") if opt.get("delta") is not None else greeks.get("delta")
            )
            logger.debug(f"iv={iv} (type: {type(iv)})")
            if strike is None or iv is None:
                continue
            try:
                strike_f = float(strike)
                distance = abs(strike_f - float(spot))
                iv_f = float(iv)
                delta_f = float(delta) if delta is not None else None
            except Exception as e:
                logger.warning(f"Skipping option due to conversion error: {e}")
                continue
            if delta_f is not None and (delta_f < 0.05 or delta_f > 0.95):
                continue
            iv_candidates.append((distance, iv_f, strike_f))
        if not iv_candidates:
            logger.warning(f"No valid IV candidates found for ATM call of {symbol}")
            return None, None
        iv_candidates.sort(key=lambda c: c[0])
        best = iv_candidates[0]
        logger.info(
            f"Selected ATM call: distance={best[0]:.2f} iv={best[1]} strike={best[2]}"
        )
        return best[1], best[2]


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

    # Save raw option data for debugging
    debug_dir = Path(cfg_get("IV_DEBUG_DIR", "iv_debug"))
    debug_dir.mkdir(parents=True, exist_ok=True)
    debug_file = debug_dir / f"{symbol}.log"
    with debug_file.open("w", encoding="utf-8") as df:
        for opt in opts1:
            strike = (
                opt.get("strike_price")
                or opt.get("strike")
                or opt.get("exercise_price")
            )
            greeks = opt.get("greeks") or {}
            iv = opt.get("implied_volatility") or opt.get("iv") or greeks.get("iv")
            delta = (
                opt.get("delta")
                if opt.get("delta") is not None
                else greeks.get("delta")
            )
            df.write(f"{strike},{delta},{iv}\n")
    atm_iv_skew, call_iv, put_iv = IVExtractor.extract_skew(opts1, spot)
    _export_option_chain(symbol, opts1)
    atm_iv_fallback, atm_strike = IVExtractor.extract_atm_call(opts1, spot, symbol)
    if atm_iv_skew is None and atm_iv_fallback is not None:
        logger.info(f"Selected ATM fallback IV from strike {atm_strike}")
    atm_iv = atm_iv_skew if atm_iv_skew is not None else atm_iv_fallback

    iv_month2 = iv_month3 = None
    if month2:
        opts2 = fetcher.fetch_expiry(symbol, month2.strftime("%Y-%m-%d"))
        iv_month2, _ = IVExtractor.extract_atm_call(opts2, spot, symbol)
    if month3:
        opts3 = fetcher.fetch_expiry(symbol, month3.strftime("%Y-%m-%d"))
        iv_month3, _ = IVExtractor.extract_atm_call(opts3, spot, symbol)

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
