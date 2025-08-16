from __future__ import annotations

"""Helpers for retrieving IV data from the Polygon API."""

from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any, Dict, List
from tomic.utils import today
from tomic.utils import _is_third_friday, _is_weekly
import json
import time
import csv

from tomic.analysis.metrics import historical_volatility

from tomic.polygon_client import PolygonClient

from tomic.config import get as cfg_get
from tomic.logutils import logger
from tomic.journal.utils import load_json, update_json_file
from tomic.helpers.price_utils import _load_latest_close


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------




def _get_closes(symbol: str) -> list[float]:
    """Return list of closing prices sorted by date for ``symbol``."""
    base = Path(cfg_get("PRICE_HISTORY_DIR", "tomic/data/spot_prices"))
    path = base / f"{symbol}.json"
    data = load_json(path)
    if not isinstance(data, list):
        return []
    data.sort(key=lambda r: r.get("date", ""))
    closes: list[float] = []
    for rec in data:
        try:
            closes.append(float(rec.get("close", 0)))
        except Exception:
            continue
    return closes


def _rolling_hv(closes: list[float], window: int) -> list[float]:
    """Return list of HV values for a rolling ``window``."""
    series: list[float] = []
    for i in range(window, len(closes) + 1):
        hv = historical_volatility(closes[i - window : i], window=window)
        if hv is not None:
            series.append(hv)
    return series


def _iv_rank(value: float, series: list[float]) -> float | None:
    nums = [s for s in series if isinstance(s, (int, float))]
    if not nums:
        return None
    lo = min(nums)
    hi = max(nums)
    if hi == lo:
        return None
    return (value - lo) / (hi - lo)


def _iv_percentile(value: float, series: list[float]) -> float | None:
    nums = [s for s in series if isinstance(s, (int, float))]
    if not nums:
        return None
    count = sum(1 for hv in nums if hv < value)
    return count / len(nums)


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

    def __init__(self, api_key: str | None) -> None:
        self.client = PolygonClient(api_key=api_key)

    def fetch_expiry(self, symbol: str, expiry: str) -> List[Dict[str, Any]]:
        path = f"v3/snapshot/options/{symbol.upper()}"
        params = {"expiration_date": expiry}
        options: List[Dict[str, Any]] = []
        next_path: str | None = path
        first = True
        self.client.connect()
        try:
            while next_path:
                params_to_use = params if first else {}
                if first:
                    logger.info(f"Requesting snapshot for {symbol} {expiry}")
                payload = self.client._request(next_path, params_to_use)
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
                if next_url:
                    if not next_url.startswith("http"):
                        next_path = next_url.lstrip("/")
                    else:
                        base = self.client.BASE_URL.rstrip("/")
                        next_path = next_url[len(base) + 1 :] if next_url.startswith(base) else next_url
                    time.sleep(0.2)
                else:
                    next_path = None
                if first:
                    first = False
        except Exception as exc:  # pragma: no cover - network failure
            logger.warning(f"Polygon request failed for {symbol}: {exc}")
        finally:
            self.client.disconnect()
        logger.info(f"{symbol} {expiry}: {len(options)} contracts")
        delay_ms = int(cfg_get("POLYGON_DELAY_SNAPSHOT_MS", 200))
        if delay_ms > 0:
            time.sleep(delay_ms / 1000)
        return options


def load_polygon_expiries(
    symbol: str, api_key: str | None = None, *, include_contracts: bool = False
) -> list[str] | tuple[list[str], dict[str, List[Dict[str, Any]]]]:
    """Return upcoming expiries for ``symbol`` using Polygon.

    When ``include_contracts`` is ``True`` the return value is a tuple of the
    list of valid expiries and a mapping of expiries to their option contracts.
    Otherwise only the list of expiries is returned (default behaviour).
    """

    today_date = today()

    reg_count = int(cfg_get("AMOUNT_REGULARS", 3))
    week_count = int(cfg_get("AMOUNT_WEEKLIES", 4))
    weekly_min_dte = int(cfg_get("WEEKLY_EXPIRIES_MIN_DTE", 15))

    # Determine the next third Friday within the desired window and the
    # following ``reg_count`` “regular” expiries.
    third_fridays = ExpiryPlanner.get_next_third_fridays(
        start=today_date, count=reg_count + 2
    )
    first_idx = None
    for idx, dt in enumerate(third_fridays):
        dte = (dt - today_date).days
        if 15 <= dte <= 45:
            first_idx = idx
            break
    if first_idx is None:
        logger.warning(f"No third Friday between 15 and 45 DTE for {symbol}")
        first_idx = 0

    monthlies: list[str] = []
    for dt in third_fridays[first_idx : first_idx + reg_count]:
        monthlies.append(dt.strftime("%Y-%m-%d"))

    # Determine upcoming weekly expiries
    weeklies: list[str] = []
    check = today_date + timedelta(days=1)
    while len(weeklies) < week_count and (check - today_date).days <= 120:
        if check.weekday() == 4 and not _is_third_friday(check):
            dte = (check - today_date).days
            if weekly_min_dte <= dte:
                weeklies.append(check.strftime("%Y-%m-%d"))
        check += timedelta(days=1)

    candidate_expiries = monthlies + weeklies

    fetcher = SnapshotFetcher(api_key)
    valid_expiries: list[str] = []
    options_by_expiry: dict[str, List[Dict[str, Any]]] = {}
    for expiry in candidate_expiries:
        contracts: list[Dict[str, Any]] = []
        try:
            contracts = fetcher.fetch_expiry(symbol, expiry)
        except Exception as exc:  # pragma: no cover - network failure
            logger.warning(f"Polygon snapshot failed for {symbol} {expiry}: {exc}")
        if any(isinstance(c, dict) for c in contracts):
            valid_expiries.append(expiry)
            if include_contracts:
                options_by_expiry[expiry] = contracts
        else:
            logger.warning(
                f"Expiry {expiry} bevat geen contracten en wordt overgeslagen"
            )

    return (valid_expiries, options_by_expiry) if include_contracts else valid_expiries


def _export_option_chain(symbol: str, options: List[Dict[str, Any]]) -> None:
    """Write option chain to CSV using today's date and timestamp."""
    base = Path(cfg_get("EXPORT_DIR", "exports"))
    base.mkdir(exist_ok=True)
    date_dir = base / datetime.now().strftime("%Y%m%d")
    date_dir.mkdir(parents=True, exist_ok=True)
    filename = (
        f"{symbol}_{datetime.now().strftime('%Y-%m-%d-%H-%M')}-optionchainpolygon.csv"
    )
    path = date_dir / filename
    if not options or not any(isinstance(o, dict) for o in options):
        logger.warning(f"No valid option contracts to export for {symbol}")
        return
    headers = [
        "Expiry",
        "Type",
        "Strike",
        "Bid",
        "Ask",
        "Close",
        "IV",
        "Delta",
        "Gamma",
        "Vega",
        "Theta",
        "Volume",
        "OpenInterest",
    ]
    def _round(val: Any) -> Any:
        try:
            return round(float(val), 4)
        except Exception:
            return val

    try:
        def _extract_key_metrics(opt: Dict[str, Any]):
            details = opt.get("details") or {}
            day = opt.get("day") or {}
            strike_raw = (
                opt.get("strike_price")
                or opt.get("strike")
                or opt.get("exercise_price")
                or details.get("strike_price")
            )
            try:
                strike_f = float(strike_raw)
                strike_out = int(strike_f) if strike_f.is_integer() else round(strike_f, 2)
            except Exception:
                strike_out = strike_raw
            expiry = (
                opt.get("expiration_date")
                or opt.get("expDate")
                or opt.get("expiry")
                or details.get("expiration_date")
                or details.get("expiry")
                or details.get("expDate")
            )
            opt_type = (
                opt.get("option_type")
                or opt.get("type")
                or opt.get("contract_type")
                or details.get("contract_type")
                or opt.get("right")
            )
            bid = (
                opt.get("bid")
                or opt.get("bid_price")
                or (opt.get("last_quote") or {}).get("bid")
                or details.get("bid")
            )
            ask = (
                opt.get("ask")
                or opt.get("ask_price")
                or (opt.get("last_quote") or {}).get("ask")
                or details.get("ask")
            )
            volume = opt.get("volume") or day.get("volume") or day.get("v")
            return (expiry, opt_type, strike_out), bid, ask, volume

        groups: Dict[tuple[Any, Any, Any], Dict[str, Any]] = {}
        metrics: Dict[tuple[Any, Any, Any], tuple[bool, float]] = {}
        for opt in options:
            key, bid, ask, volume = _extract_key_metrics(opt)
            has_ba = bid is not None and ask is not None
            vol_val = float(volume) if isinstance(volume, (int, float)) else 0.0
            if key not in groups:
                groups[key] = opt
                metrics[key] = (has_ba, vol_val)
            else:
                best_ba, best_vol = metrics[key]
                if has_ba and not best_ba:
                    groups[key] = opt
                    metrics[key] = (has_ba, vol_val)
                elif has_ba == best_ba and vol_val > best_vol:
                    groups[key] = opt
                    metrics[key] = (has_ba, vol_val)

        def _sort_key(k: tuple[Any, Any, Any]):
            exp, typ, strike = k
            try:
                strike_val = float(strike)
            except Exception:
                strike_val = float("inf")
            return (exp or "", typ or "", strike_val)

        with path.open("w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(headers)
            for key in sorted(groups.keys(), key=_sort_key):
                opt = groups[key]
                greeks = opt.get("greeks") or {}
                day = opt.get("day") or {}
                details = opt.get("details") or {}
                # recompute values for output to ensure consistency
                strike_raw = (
                    opt.get("strike_price")
                    or opt.get("strike")
                    or opt.get("exercise_price")
                    or details.get("strike_price")
                )
                try:
                    strike_f = float(strike_raw)
                    strike_out = int(strike_f) if strike_f.is_integer() else round(strike_f, 2)
                except Exception:
                    strike_out = strike_raw
                expiry = (
                    opt.get("expiration_date")
                    or opt.get("expDate")
                    or opt.get("expiry")
                    or details.get("expiration_date")
                    or details.get("expiry")
                    or details.get("expDate")
                )
                iv = (
                    opt.get("implied_volatility")
                    or opt.get("iv")
                    or greeks.get("iv")
                )
                delta = opt.get("delta") if opt.get("delta") is not None else greeks.get("delta")
                gamma = opt.get("gamma") if opt.get("gamma") is not None else greeks.get("gamma")
                theta = opt.get("theta") if opt.get("theta") is not None else greeks.get("theta")
                vega = opt.get("vega") if opt.get("vega") is not None else greeks.get("vega")
                bid = (
                    opt.get("bid")
                    or opt.get("bid_price")
                    or (opt.get("last_quote") or {}).get("bid")
                    or details.get("bid")
                )
                ask = (
                    opt.get("ask")
                    or opt.get("ask_price")
                    or (opt.get("last_quote") or {}).get("ask")
                    or details.get("ask")
                )
                open_interest = opt.get("open_interest") or details.get("open_interest")
                writer.writerow(
                    [
                        expiry,
                        opt.get("option_type")
                        or opt.get("type")
                        or opt.get("contract_type")
                        or details.get("contract_type")
                        or opt.get("right"),
                        strike_out,
                        _round(bid),
                        _round(ask),
                        opt.get("close") or day.get("close") or day.get("c"),
                        _round(iv),
                        _round(delta),
                        _round(gamma),
                        _round(vega),
                        _round(theta),
                        opt.get("volume") or day.get("volume") or day.get("v"),
                        open_interest,
                    ]
                )
        if not path.exists():
            logger.error(f"Failed to export option chain to {path.resolve()}")
        else:
            logger.info(f"Exported option chain to {path.resolve()}")
    except Exception as exc:  # pragma: no cover - filesystem errors
        logger.error(f"Failed to export option chain to {path.resolve()}: {exc}")



# ---------------------------------------------------------------------------
# IV extraction
# ---------------------------------------------------------------------------


class IVExtractor:
    """Extract ATM and skew information from option lists."""

    @staticmethod
    def extract_skew(
        options: List[Dict[str, Any]],
        spot: float,
        *,
        symbol: str | None = None,
        expiry: str | None = None,
    ) -> tuple[float | None, float | None, float | None]:
        # ------------------------------------------------------------------
        # Deduplicate options by strike and type
        # Polygon occasionally returns multiple entries for the same contract.
        # To avoid skewed calculations we keep the most reliable entry for
        # each (strike, type) pair. Reliability is determined first by the
        # highest reported volume and then by the latest timestamp.
        # ------------------------------------------------------------------
        grouped: dict[tuple[float, str], Dict[str, Any]] = {}

        def _get_volume(o: Dict[str, Any]) -> float:
            vol = o.get("volume")
            if vol is None and isinstance(o.get("day"), dict):
                vol = o["day"].get("volume")
            if vol is None and isinstance(o.get("details"), dict):
                vol = o["details"].get("volume")
            try:
                return float(vol)
            except Exception:
                return 0.0

        def _get_updated(o: Dict[str, Any]) -> float:
            for key in ("last_updated", "updated", "t", "timestamp"):
                ts = o.get(key)
                if ts is None and isinstance(o.get("details"), dict):
                    ts = o["details"].get(key)
                if ts is not None:
                    try:
                        return float(ts)
                    except Exception:
                        continue
            return 0.0

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
                    or (details.get("strike_price") if isinstance(details, dict) else None)
            )

            if right is None or strike is None:
                continue
            try:
                strike_f = float(strike)
            except Exception:
                continue
            key = (strike_f, str(right).lower())
            existing = grouped.get(key)
            if existing is None:
                grouped[key] = opt
            else:
                existing_vol = _get_volume(existing)
                new_vol = _get_volume(opt)
                if new_vol > existing_vol or (
                    new_vol == existing_vol and _get_updated(opt) > _get_updated(existing)
                ):
                    grouped[key] = opt

        options = list(grouped.values())
        options.sort(key=lambda o: float(o.get("strike_price") or o.get("strike") or 0))
        logger.info(f"extract_skew: {len(options)} options after dedup")
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
                    or (details.get("strike_price") if isinstance(details, dict) else None)
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
                if str(right).lower().startswith("c") and 0.05 <= delta_f <= 0.45:
                    in_range += 1
                if str(right).lower().startswith("c"):
                    seen_call_delta = True
                elif (
                    str(right).lower().startswith("p")
                    and 0.05 <= abs(delta_f) <= 0.45
                    and delta_f < 0
                ):
                    in_range += 1
                if str(right).lower().startswith("p"):
                    seen_put_delta = True

            if str(right).lower().startswith("c") and 0.05 <= delta_f <= 0.45:
                diff_c = abs(delta_f - 0.25)
                if best_call_diff is None or diff_c < best_call_diff:
                    logger.debug(
                        f"call-option candidate: strike={strike_f}, delta={delta_f}, iv={iv_f}"
                    )
                    best_call_diff = diff_c
                    call_iv = iv_f
            elif (
                str(right).lower().startswith("p")
                and 0.05 <= abs(delta_f) <= 0.45
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

        if call_iv is None or put_iv is None:
            if symbol and expiry:
                logger.warning(
                    f"Could not extract skew for {symbol} {expiry}: no suitable delta-25 options found"
                )
            else:
                logger.warning("Missing call or put delta for skew calculation")

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
                    or (details.get("strike_price") if isinstance(details, dict) else None)
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


def fetch_polygon_iv30d(symbol: str) -> Dict[str, float | None] | None:
    """Return volatility metrics for ``symbol`` using filtered snapshots."""
    spot, spot_date = _load_latest_close(symbol)
    if spot is None or spot_date is None:
        logger.warning(f"No price history for {symbol}")
        return {"atm_iv": None, "skew": None, "term_m1_m2": None, "term_m1_m3": None}

    summary_file = Path(cfg_get("IV_SUMMARY_DIR", "tomic/data/iv_daily_summary")) / f"{symbol}.json"
    if summary_file.exists():
        existing = load_json(summary_file)
        for row in existing:
            if not isinstance(row, dict) or row.get("date") != spot_date:
                continue
            if row.get("atm_iv") is not None:
                logger.info(
                    f"⏭️ {symbol} on {spot_date} already in summary file, skipping snapshot fetch."
                )
                return None
            logger.info(
                f"♻️ {symbol} on {spot_date} has null IV, attempting refetch."
            )
            break

    api_key = cfg_get("POLYGON_API_KEY", "")
    spot = round(float(spot), 2)

    today_dt = datetime.now(ZoneInfo("America/New_York")).date()
    expiries = ExpiryPlanner.get_next_third_fridays(today_dt, count=4)

    target: date | None = None
    for exp in expiries:
        dte = (exp - today_dt).days
        if 13 <= dte <= 48:
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
    if not opts1:
        logger.warning(f"No contracts found for symbol {symbol}")
        return None

    # Save raw option data for debugging
    debug_dir = Path(cfg_get("IV_DEBUG_DIR", "iv_debug"))
    debug_dir.mkdir(parents=True, exist_ok=True)
    debug_file = debug_dir / f"{symbol}.log"
    with debug_file.open("w", encoding="utf-8") as df:
        for opt in opts1:

            details = opt.get("details") or {}
            strike = (
                    opt.get("strike_price")
                    or opt.get("strike")
                    or opt.get("exercise_price")
                    or details.get("strike_price")
            )

            greeks = opt.get("greeks") or {}
            iv = opt.get("implied_volatility") or opt.get("iv") or greeks.get("iv")
            delta = (
                opt.get("delta")
                if opt.get("delta") is not None
                else greeks.get("delta")
            )
            df.write(f"{strike},{delta},{iv}\n")
    atm_iv_skew, call_iv, put_iv = IVExtractor.extract_skew(
        opts1, spot, symbol=symbol, expiry=target.strftime("%Y-%m-%d")
    )
    if opts1:
        _export_option_chain(symbol, opts1)
    else:
        logger.warning(f"No contracts to export for {symbol}")
    atm_fallback, atm_strike = IVExtractor.extract_atm_call(opts1, spot, symbol)
    if atm_iv_skew is None and atm_fallback is not None:
        logger.info(f"Selected ATM fallback IV from strike {atm_strike}")

    #atm_iv = atm_iv_skew if isinstance(atm_iv_skew, (int, float)) else None
    logger.debug(f"atm_iv_skew={atm_iv_skew} (type: {type(atm_iv_skew)})")

    try:
        atm_iv = float(atm_iv_skew)
    except (TypeError, ValueError):
        atm_iv = None
    logger.debug(f"atm_iv_skew={atm_iv_skew} (type: {type(atm_iv_skew)})")

    if atm_iv is None and isinstance(atm_fallback, (int, float)):
        logger.info(f"Selected ATM fallback IV from strike {atm_strike}")
        atm_iv = atm_fallback
    if atm_iv is None and isinstance(call_iv, (int, float)):
        atm_iv = call_iv
    if atm_iv is None:
        logger.error(
            f"ATM IV could not be determined for {symbol} on {target.strftime('%Y-%m-%d')}"
        )

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
    else:
        if atm_iv is None or iv_month2 is None:
            logger.debug(
                f"term_m1_m2 unavailable: atm_iv={atm_iv} iv_month2={iv_month2}"
            )
    if atm_iv is not None and iv_month3 is not None:
        term_m1_m3 = round((atm_iv - iv_month3) * 100, 2)
    else:
        if atm_iv is None or iv_month3 is None:
            logger.debug(
                f"term_m1_m3 unavailable: atm_iv={atm_iv} iv_month3={iv_month3}"
            )

    skew = None
    if call_iv is not None and put_iv is not None:
        skew = round((put_iv - call_iv) * 100, 2)
    else:
        logger.debug(f"skew unavailable: call_iv={call_iv} put_iv={put_iv}")

    iv_rank = None
    iv_percentile = None
    closes = _get_closes(symbol)
    hv_series = _rolling_hv(closes, 30)
    if atm_iv is not None:
        scaled_iv = atm_iv * 100
        iv_rank = _iv_rank(scaled_iv, hv_series)
        iv_percentile = _iv_percentile(scaled_iv, hv_series)
    else:
        logger.debug("Cannot compute IV rank without ATM IV")

    today_str = spot_date  # gebruik de datum van de laatste close
    daily_iv_data = {
        "date": today_str,
        "atm_iv": atm_iv,
        "iv_rank (HV)": iv_rank,
        "iv_percentile (HV)": iv_percentile,
        "term_m1_m2": term_m1_m2,
        "term_m1_m3": term_m1_m3,
        "skew": skew,
    }
    logger.debug(f"✅ Summary data for {symbol}: {json.dumps(daily_iv_data, indent=2)}")

    summary_dir = Path(cfg_get("IV_SUMMARY_DIR", "tomic/data/iv_daily_summary"))
    summary_dir.mkdir(parents=True, exist_ok=True)
    summary_file = summary_dir / f"{symbol}.json"

    try:
        update_json_file(summary_file, daily_iv_data, ["date"])
        logger.info(f"✅ Updated {summary_file}")
    except Exception as exc:
        logger.error(f"❌ Failed to update {summary_file}: {exc}")

    return {
        "atm_iv": atm_iv,
        "skew": skew,
        "term_m1_m2": term_m1_m2,
        "term_m1_m3": term_m1_m3,
        "iv_rank (HV)": iv_rank,
        "iv_percentile (HV)": iv_percentile,
    }


def fetch_polygon_option_chain(symbol: str) -> None:
    """Export a Polygon option chain filtered by delta range."""

    api_key = cfg_get("POLYGON_API_KEY", "")
    expiries, options_map = load_polygon_expiries(
        symbol, api_key, include_contracts=True
    )
    if not expiries:
        logger.warning(f"No expiries found for {symbol}")
        return

    d_min = float(cfg_get("DELTA_MIN", -1))
    d_max = float(cfg_get("DELTA_MAX", 1))

    total_before = sum(len(v) for v in options_map.values())
    logger.info(f"{symbol}: {total_before} contracts before delta filter")

    filtered: list[dict] = []
    for exp in expiries:
        before = len(options_map.get(exp, []))
        kept = 0
        for opt in options_map.get(exp, []):
            greeks = opt.get("greeks") or {}
            delta = opt.get("delta") if opt.get("delta") is not None else greeks.get("delta")
            try:
                delta_f = float(delta) if delta is not None else None
            except Exception:
                delta_f = None
            if delta_f is not None and (delta_f < d_min or delta_f > d_max):
                continue
            filtered.append(opt)
            kept += 1
        logger.info(f"Expiry {exp}: {before} -> {kept} after delta filter")

    _export_option_chain(symbol, filtered)


__all__ = [
    "fetch_polygon_iv30d",
    "fetch_polygon_option_chain",
    "load_polygon_expiries",
]
