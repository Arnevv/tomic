from __future__ import annotations

"""Process Polygon flatfiles into ``iv_daily_summary`` records."""

import argparse
import gzip
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from tomic.config import get as cfg_get
from tomic.journal.utils import load_json, update_json_file
from tomic.logutils import logger, setup_logging
from tomic.providers.polygon_iv import (
    IVExtractor,
    ExpiryPlanner,
    _rolling_hv,
    _iv_rank,
    _iv_percentile,
)


def _get_closes(symbol: str) -> List[float]:
    base = Path(cfg_get("PRICE_HISTORY_DIR", "tomic/data/spot_prices"))
    data = load_json(base / f"{symbol}.json")
    if not isinstance(data, list):
        return []
    data.sort(key=lambda r: r.get("date", ""))
    closes: List[float] = []
    for rec in data:
        try:
            closes.append(float(rec.get("close", 0)))
        except Exception:
            continue
    return closes


def _get_close_for_date(symbol: str, date_str: str) -> float | None:
    base = Path(cfg_get("PRICE_HISTORY_DIR", "tomic/data/spot_prices"))
    data = load_json(base / f"{symbol}.json")
    if isinstance(data, list):
        for rec in data:
            if str(rec.get("date")) == date_str:
                try:
                    return float(rec.get("close"))
                except Exception:
                    return None
    return None


def _load_options(file: Path, symbols: set[str]) -> Dict[str, List[dict]]:
    result: Dict[str, List[dict]] = {s: [] for s in symbols}
    with gzip.open(file, "rt", encoding="utf-8") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            sym = str(rec.get("underlying_ticker") or "").upper()
            if sym in symbols:
                result.setdefault(sym, []).append(rec)
    return result


def _compute_metrics_for_symbol(options: List[dict], symbol: str, date_str: str) -> Dict[str, float | None] | None:
    spot = _get_close_for_date(symbol, date_str)
    if spot is None:
        logger.warning(f"No price for {symbol} on {date_str}")
        return None

    dt = datetime.strptime(date_str, "%Y-%m-%d").date()
    expiries = ExpiryPlanner.get_next_third_fridays(dt, count=4)

    by_exp: Dict[str, List[dict]] = {}
    for opt in options:
        exp_raw = opt.get("expiration_date") or opt.get("expDate")
        if exp_raw is None:
            continue
        try:
            if "-" in str(exp_raw):
                exp_dt = datetime.strptime(str(exp_raw)[:10], "%Y-%m-%d").date()
            else:
                exp_dt = datetime.strptime(str(exp_raw), "%Y%m%d").date()
        except Exception:
            continue
        by_exp.setdefault(exp_dt.strftime("%Y-%m-%d"), []).append(opt)

    target: datetime.date | None = None
    for exp in expiries:
        dte = (exp - dt).days
        if 15 <= dte <= 45:
            target = exp
            break
    if target is None:
        logger.warning(f"No suitable expiry for {symbol} on {date_str}")
        return None
    idx = expiries.index(target)
    month2 = expiries[idx + 1] if idx + 1 < len(expiries) else None
    month3 = expiries[idx + 2] if idx + 2 < len(expiries) else None

    opts1 = by_exp.get(target.strftime("%Y-%m-%d"), [])
    atm_iv_skew, call_iv, put_iv = IVExtractor.extract_skew(
        opts1, spot, symbol=symbol, expiry=target.strftime("%Y-%m-%d")
    )
    atm_fallback, _ = IVExtractor.extract_atm_call(opts1, spot, symbol)

    atm_iv: float | None = None
    try:
        atm_iv = float(atm_iv_skew)
    except Exception:
        pass
    if atm_iv is None and isinstance(atm_fallback, (int, float)):
        atm_iv = atm_fallback
    if atm_iv is None and isinstance(call_iv, (int, float)):
        atm_iv = call_iv

    iv_month2 = iv_month3 = None
    if month2:
        opts2 = by_exp.get(month2.strftime("%Y-%m-%d"), [])
        iv_month2, _ = IVExtractor.extract_atm_call(opts2, spot, symbol)
    if month3:
        opts3 = by_exp.get(month3.strftime("%Y-%m-%d"), [])
        iv_month3, _ = IVExtractor.extract_atm_call(opts3, spot, symbol)

    term_m1_m2 = (
        round((atm_iv - iv_month2) * 100, 2) if atm_iv is not None and iv_month2 is not None else None
    )
    term_m1_m3 = (
        round((atm_iv - iv_month3) * 100, 2) if atm_iv is not None and iv_month3 is not None else None
    )
    skew = round((put_iv - call_iv) * 100, 2) if call_iv is not None and put_iv is not None else None

    closes = _get_closes(symbol)
    hv_series = _rolling_hv(closes, 30)
    iv_rank = None
    iv_percentile = None
    if atm_iv is not None:
        scaled = atm_iv * 100
        iv_rank = _iv_rank(scaled, hv_series)
        iv_percentile = _iv_percentile(scaled, hv_series)

    return {
        "date": date_str,
        "atm_iv": atm_iv,
        "iv_rank (HV)": iv_rank,
        "iv_percentile (HV)": iv_percentile,
        "term_m1_m2": term_m1_m2,
        "term_m1_m3": term_m1_m3,
        "skew": skew,
    }


def main(argv: List[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Import Polygon flatfiles")
    parser.add_argument("--dir", dest="dir", help="Directory with flatfiles", default=None)
    parser.add_argument("--keep", action="store_true", help="Keep processed files")
    parser.add_argument("symbols", nargs="*")
    args = parser.parse_args(argv)

    setup_logging()
    logger.info("🚀 Processing Polygon flatfiles")

    symbols = [s.upper() for s in args.symbols] if args.symbols else [s.upper() for s in cfg_get("DEFAULT_SYMBOLS", [])]
    flat_dir = Path(args.dir or cfg_get("FLATFILE_DIR", "tomic/data/flatfiles"))
    summary_dir = Path(cfg_get("IV_DAILY_SUMMARY_DIR", "tomic/data/iv_daily_summary"))

    files = sorted(flat_dir.glob("options_*.json.gz"))
    if not files:
        logger.warning(f"No files found in {flat_dir}")
        return

    file_re = re.compile(r"options_(\d{4}-\d{2}-\d{2})\.json\.gz")
    for fp in files:
        m = file_re.match(fp.name)
        if not m:
            logger.warning(f"Skipping file {fp.name}")
            continue
        date_str = m.group(1)
        opts_by_symbol = _load_options(fp, set(symbols))
        for sym, opts in opts_by_symbol.items():
            if not opts:
                continue
            metrics = _compute_metrics_for_symbol(opts, sym, date_str)
            if metrics:
                update_json_file(summary_dir / f"{sym}.json", metrics, ["date"])
                logger.info(f"Saved summary for {sym} on {date_str}")
        if not args.keep:
            fp.unlink()
            logger.info(f"Removed {fp}")
    logger.success("✅ Flatfile processing complete")


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])

