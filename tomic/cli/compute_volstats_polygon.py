from __future__ import annotations

"""Compute daily volatility statistics using Polygon IV data."""

from datetime import datetime
from pathlib import Path
from time import sleep
from typing import List, Any

from tomic.analysis.metrics import historical_volatility
from tomic.config import get as cfg_get
from tomic.journal.utils import load_json, update_json_file
from tomic.logutils import logger, setup_logging
from tomic.providers.polygon_iv import fetch_polygon_iv30d
from tomic.polygon_client import PolygonClient
from tomic.helpers.price_utils import _load_latest_close


def _get_closes(symbol: str) -> list[float]:
    """Return list of close prices for ``symbol`` sorted by date."""
    base = Path(cfg_get("PRICE_HISTORY_DIR", "tomic/data/spot_prices"))
    path = base / f"{symbol}.json"
    data = load_json(path)
    if not isinstance(data, list):
        return []
    data.sort(key=lambda r: r.get("date", ""))
    return [float(rec.get("close", 0)) for rec in data]



def _polygon_term_and_skew(symbol: str) -> tuple[float | None, float | None, float | None]:
    """Compute term structure and skew metrics using Polygon snapshot data."""
    spot, spot_date = _load_latest_close(symbol)
    if spot is None or spot_date is None:
        return None, None, None

    client = PolygonClient()
    client.connect()
    path = f"v3/snapshot/options/{symbol.upper()}"
    try:
        payload = client._request(path, params={})
    except Exception as exc:  # pragma: no cover - network failure
        logger.warning(f"Polygon request failed for {symbol}: {exc}")
        client.disconnect()
        return None, None, None
    client.disconnect()

    results = payload.get("results", {})
    if isinstance(results, dict):
        options: List[dict[str, Any]] = results.get("options") or []
    elif isinstance(results, list):  # pragma: no cover - alt structure
        options = results
    else:
        options = []
    if not options:
        return None, None, None

    spot_dt = datetime.strptime(spot_date, "%Y-%m-%d").date()

    grouped: dict[str, list[float]] = {}
    call_iv: float | None = None
    put_iv: float | None = None
    call_err = float("inf")
    put_err = float("inf")
    call_strike_err = float("inf")
    put_strike_err = float("inf")

    target_call = spot * 1.15
    target_put = spot * 0.85

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
        right = (
            opt.get("option_type")
            or opt.get("type")
            or opt.get("contract_type")
            or opt.get("details", {}).get("contract_type")
            or opt.get("right")
        )
        delta = opt.get("delta") or opt.get("greeks", {}).get("delta")
        try:
            if "-" in str(exp_raw):
                exp_dt = datetime.strptime(str(exp_raw), "%Y-%m-%d").date()
            else:
                exp_dt = datetime.strptime(str(exp_raw), "%Y%m%d").date()
            strike_f = float(strike)
            iv_f = float(iv)
        except Exception:
            continue

        tolerance = max(spot * 0.03, 2.0)
        if abs(strike_f - spot) <= tolerance:
            grouped.setdefault(str(exp_dt), []).append(iv_f)

        if right:
            r = str(right).lower()
        else:
            r = ""

        if delta is not None:
            try:
                d = float(delta)
                if r.startswith("c"):
                    err = abs(d - 0.25)
                    if err < call_err:
                        call_err = err
                        call_iv = iv_f
                elif r.startswith("p"):
                    err = abs(d + 0.25)
                    if err < put_err:
                        put_err = err
                        put_iv = iv_f
            except Exception:
                pass
        else:
            if r.startswith("c"):
                diff = abs(strike_f - target_call)
                if diff < call_strike_err:
                    call_strike_err = diff
                    call_iv = iv_f
            elif r.startswith("p"):
                diff = abs(strike_f - target_put)
                if diff < put_strike_err:
                    put_strike_err = diff
                    put_iv = iv_f

    avgs: list[float] = []
    for exp in sorted(grouped.keys()):
        ivs = grouped[exp]
        if ivs:
            avgs.append(sum(ivs) / len(ivs))

    term_m1_m2 = round((avgs[0] - avgs[1]) * 100, 2) if len(avgs) >= 2 else None
    term_m1_m3 = round((avgs[0] - avgs[2]) * 100, 2) if len(avgs) >= 3 else None

    skew = None
    if call_iv is not None and put_iv is not None:
        skew = round((put_iv - call_iv) * 100, 2)
    else:
        logger.debug(
            f"Skew unavailable for {symbol}: call_iv={call_iv} put_iv={put_iv}"
        )

    return term_m1_m2, term_m1_m3, skew


def main(argv: List[str] | None = None) -> None:
    """Compute volatility stats for provided or default symbols."""
    setup_logging()
    logger.info("🚀 Computing volatility stats (Polygon)")
    if argv is None:
        argv = []
    symbols = [s.upper() for s in argv] if argv else [s.upper() for s in cfg_get("DEFAULT_SYMBOLS", [])]
    raw_max = cfg_get("MAX_SYMBOLS_PER_RUN")
    try:
        max_syms = int(raw_max) if raw_max is not None else None
    except (TypeError, ValueError):
        max_syms = None
    sleep_between = float(cfg_get("POLYGON_SLEEP_BETWEEN", 1.2))

    summary_dir = Path(cfg_get("IV_DAILY_SUMMARY_DIR", "tomic/data/iv_daily_summary"))
    hv_dir = Path(cfg_get("HISTORICAL_VOLATILITY_DIR", "tomic/data/historical_volatility"))

    def rolling_hv(closes: list[float], window: int) -> list[float]:
        result = []
        for i in range(window, len(closes) + 1):
            hv = historical_volatility(closes[i - window : i], window=window)
            if hv is not None:
                result.append(hv)
        return result

    def iv_rank(value: float, series: list[float]) -> float | None:
        if not series:
            return None
        lo = min(series)
        hi = max(series)
        if hi == lo:
            return None
        return (value - lo) / (hi - lo)

    def iv_percentile(value: float, series: list[float]) -> float | None:
        if not series:
            return None
        count = sum(1 for hv in series if hv < value)
        return count / len(series)

    for idx, sym in enumerate(symbols):
        if max_syms is not None and idx >= max_syms:
            break
        close_price, date_str = _load_latest_close(sym)
        closes = _get_closes(sym)
        if close_price is not None and closes:
            if closes[-1] != close_price:
                closes.append(close_price)
        if not closes:
            logger.warning(f"No price history for {sym}")
            continue
        hv20 = historical_volatility(closes, window=20)
        hv30 = historical_volatility(closes, window=30)
        hv90 = historical_volatility(closes, window=90)
        hv252 = historical_volatility(closes, window=252)
        metrics = fetch_polygon_iv30d(sym)
        if date_str is None:
            logger.warning(f"No price history for {sym}")
            continue

        if hv20 is not None:
            hv20 /= 100
        if hv30 is not None:
            hv30 /= 100
        if hv90 is not None:
            hv90 /= 100
        if hv252 is not None:
            hv252 /= 100

        hv_record = {
            "date": date_str,
            "hv20": hv20,
            "hv30": hv30,
            "hv90": hv90,
            "hv252": hv252,
        }
        update_json_file(hv_dir / f"{sym}.json", hv_record, ["date"])

        if metrics is None:
            logger.info(f"⏭️ {sym} already processed for {date_str}")
            sleep(sleep_between)
            continue

        iv = metrics.get("atm_iv")
        term_m1_m2 = metrics.get("term_m1_m2")
        term_m1_m3 = metrics.get("term_m1_m3")
        skew = metrics.get("skew")
        rank = metrics.get("iv_rank (HV)")
        pct = metrics.get("iv_percentile (HV)")
        if iv is None:
            logger.warning(f"No implied volatility for {sym}")
        hv_series = rolling_hv(closes, 30)
        scaled_iv = iv * 100 if iv is not None else None
        rank = iv_rank(scaled_iv or 0.0, hv_series) if scaled_iv is not None else None
        pct = iv_percentile(scaled_iv or 0.0, hv_series) if scaled_iv is not None else None
        if isinstance(rank, (int, float)) and rank > 1:
            rank /= 100
        if isinstance(pct, (int, float)) and pct > 1:
            pct /= 100

        summary_record = {
            "date": date_str,
            "atm_iv": iv,
            "iv_rank (HV)": rank,
            "iv_percentile (HV)": pct,
            "term_m1_m2": term_m1_m2,
            "term_m1_m3": term_m1_m3,
            "skew": skew,
        }
        update_json_file(summary_dir / f"{sym}.json", summary_record, ["date"])
        logger.info(f"Saved vol stats for {sym}")
        sleep(sleep_between)
    logger.success("✅ Volatility stats updated")


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
