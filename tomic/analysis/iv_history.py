from __future__ import annotations

"""Helpers for storing a small IV history subset."""

from datetime import datetime, date
from pathlib import Path
from typing import Iterable, Dict, Any, List

from tomic.config import get as cfg_get
from tomic.journal.utils import update_json_file


def _parse_expiry(raw: str) -> date | None:
    try:
        if "-" in raw:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        return datetime.strptime(raw, "%Y%m%d").date()
    except Exception:
        return None


def _nearest_strike_by_delta(records: Iterable[Dict[str, Any]], target: float, right: str) -> float | None:
    best: float | None = None
    best_diff: float | None = None
    for rec in records:
        if rec.get("right") != right:
            continue
        d = rec.get("delta")
        s = rec.get("strike")
        if d is None or s is None:
            continue
        diff = abs(float(d) - target)
        if best_diff is None or diff < best_diff:
            best = float(s)
            best_diff = diff
    return best


def extract_iv_points(
    market_data: Iterable[Dict[str, Any]],
    expiries: Iterable[str],
    *,
    spot_price: float,
    obs_date: str | None = None,
    deltas: Iterable[float] | None = None,
    lookahead: Iterable[int] | None = None,
) -> List[Dict[str, Any]]:
    """Return filtered IV records for the configured expiries and deltas."""

    if obs_date is None:
        obs_date = date.today().strftime("%Y-%m-%d")
    if deltas is None:
        deltas = [float(d) for d in cfg_get("IV_TRACKING_DELTAS", [0.25, 0.5])]
    if lookahead is None:
        lookahead = [int(x) for x in cfg_get("IV_EXPIRY_LOOKAHEAD_DAYS", [0, 30, 60])]

    today = _parse_expiry(obs_date) or date.today()
    avail = []
    for exp in expiries:
        d = _parse_expiry(exp)
        if d is not None:
            avail.append((exp, d))
    avail.sort(key=lambda x: x[1])

    selected: list[str] = []
    for days in lookahead:
        best_exp: str | None = None
        best_diff: int | None = None
        for exp, dt_exp in avail:
            diff = abs((dt_exp - today).days - days)
            if best_diff is None or diff < best_diff:
                best_exp = exp
                best_diff = diff
        if best_exp and best_exp not in selected:
            selected.append(best_exp)
        if len(selected) >= len(lookahead):
            break

    data = list(market_data)
    results: list[Dict[str, Any]] = []
    for exp in selected:
        exp_date = _parse_expiry(exp)
        if exp_date is None:
            continue
        dte = (exp_date - today).days
        exp_records = [r for r in data if r.get("expiry") == exp]
        if not exp_records:
            continue
        strikes = [float(r["strike"]) for r in exp_records if r.get("strike") is not None]
        if not strikes:
            continue
        atm = min(strikes, key=lambda s: abs(s - spot_price))
        target_strikes: list[float] = [atm]
        for d in deltas:
            d = float(d)
            if d == 0.5:
                continue
            c_strike = _nearest_strike_by_delta(exp_records, d, "C")
            if c_strike is not None:
                target_strikes.append(c_strike)
            p_strike = _nearest_strike_by_delta(exp_records, -d, "P")
            if p_strike is not None:
                target_strikes.append(p_strike)
        for strike in sorted(set(target_strikes)):
            for right in ("C", "P"):
                rec = next(
                    (
                        r
                        for r in exp_records
                        if r.get("strike") == strike and r.get("right") == right
                    ),
                    None,
                )
                if rec is None:
                    continue
                iv = rec.get("iv")
                delta = rec.get("delta")
                if iv is None:
                    continue
                results.append(
                    {
                        "date": obs_date,
                        "expiry": exp_date.strftime("%Y-%m-%d"),
                        "dte": dte,
                        "strike": strike,
                        "delta": delta,
                        "right": "CALL" if right == "C" else "PUT",
                        "iv": iv,
                    }
                )
    return results


def store_iv_history(
    symbol: str,
    market_data: Iterable[Dict[str, Any]],
    expiries: Iterable[str],
    *,
    spot_price: float,
    obs_date: str | None = None,
    base_dir: Path | None = None,
) -> None:
    """Store selected IV records for ``symbol``."""

    records = extract_iv_points(
        market_data,
        expiries,
        spot_price=spot_price,
        obs_date=obs_date,
    )
    if not records:
        return
    if base_dir is None:
        base_dir = Path(cfg_get("IV_HISTORY_DIR", "tomic/data/iv_history"))
    file = base_dir / f"{symbol}.json"
    for rec in records:
        update_json_file(file, rec, ["date", "expiry", "right", "strike"])


__all__ = ["extract_iv_points", "store_iv_history"]
