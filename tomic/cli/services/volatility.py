from __future__ import annotations

"""Services for computing volatility statistics."""

from datetime import datetime
from pathlib import Path
from typing import Sequence

from tomic.analysis.metrics import historical_volatility
from tomic.api.market_client import TermStructureClient, await_market_data, start_app
from tomic.config import get as cfg_get
from tomic.helpers.price_utils import _load_latest_close
from tomic.journal.utils import update_json_file
from tomic.logutils import logger
from .vol_helpers import _get_closes, iv_percentile, iv_rank, rolling_hv


def fetch_iv30d(symbol: str) -> float | None:
    """Return approximate 30-day implied volatility for ``symbol`` using TWS."""
    app = TermStructureClient(symbol)
    start_app(app)
    try:
        if not await_market_data(app, symbol):
            return None
        if app.spot_price is None:
            return None
        ivs_by_expiry: dict[str, list[float]] = {}
        strike_window = int(cfg_get("TERM_STRIKE_WINDOW", 1))
        for req_id, rec in app.market_data.items():
            if req_id in app.invalid_contracts:
                continue
            iv = rec.get("iv")
            strike = rec.get("strike")
            expiry = rec.get("expiry")
            if iv is None or strike is None or expiry is None:
                continue
            if abs(float(strike) - float(app.spot_price)) <= strike_window:
                ivs_by_expiry.setdefault(str(expiry), []).append(float(iv))
        if not ivs_by_expiry:
            return None
        first = sorted(ivs_by_expiry.keys())[0]
        ivs = ivs_by_expiry[first]
        if not ivs:
            return None
        return sum(ivs) / len(ivs)
    finally:
        app.disconnect()


def compute_volatility_stats(symbols: Sequence[str] | None = None) -> list[str]:
    """Compute and persist volatility stats for ``symbols``."""
    configured = cfg_get("DEFAULT_SYMBOLS", [])
    target_symbols = [s.upper() for s in symbols] if symbols else [s.upper() for s in configured]
    if not target_symbols:
        logger.warning("No symbols configured for volatility computation")
        return []

    summary_dir = Path(cfg_get("IV_DAILY_SUMMARY_DIR", "tomic/data/iv_daily_summary"))
    hv_dir = Path(cfg_get("HISTORICAL_VOLATILITY_DIR", "tomic/data/historical_volatility"))

    stored: list[str] = []
    for sym in target_symbols:
        closes = _get_closes(sym)
        if not closes:
            logger.warning(f"No price history for {sym}")
            continue
        hv20 = historical_volatility(closes, window=20)
        hv30 = historical_volatility(closes, window=30)
        hv90 = historical_volatility(closes, window=90)
        hv252 = historical_volatility(closes, window=252)
        iv = fetch_iv30d(sym)
        date_str = _load_latest_close(sym, return_date_only=True) or datetime.now().strftime(
            "%Y-%m-%d"
        )
        hv_series = rolling_hv(closes, 30)
        scaled_iv = iv * 100 if iv is not None else None
        rank = iv_rank(scaled_iv or 0.0, hv_series) if scaled_iv is not None else None
        pct = iv_percentile(scaled_iv or 0.0, hv_series) if scaled_iv is not None else None

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

        summary_record = {
            "date": date_str,
            "atm_iv": iv,
            "iv_rank": rank,
            "iv_percentile": pct,
        }
        update_json_file(summary_dir / f"{sym}.json", summary_record, ["date"])
        stored.append(sym)
        logger.info(f"Saved vol stats for {sym}")

    if stored:
        logger.success("✅ Volatility stats updated")
    else:
        logger.warning("⚠️ Geen volatiliteitsstatistieken opgeslagen")
    return stored


def compute_polygon_volatility_stats(symbols: Sequence[str] | None = None) -> None:
    """Delegate to the Polygon volatility computation routine."""
    from tomic.cli.compute_volstats_polygon import main as compute_volstats_polygon_main

    args = list(symbols) if symbols is not None else []
    compute_volstats_polygon_main(args)
