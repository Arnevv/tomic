import os
from datetime import datetime, date
from pathlib import Path

from tomic.config import get as cfg_get
from tomic.journal.utils import load_json


def filter_future_expiries(expirations: list[str]) -> list[str]:
    """Return expiries after :func:`today` sorted chronologically."""

    future_dates: list[date] = []
    today_date = today()
    for exp in expirations:
        try:
            dt = datetime.strptime(exp, "%Y%m%d").date()
        except Exception:
            continue
        if dt > today_date:
            future_dates.append(dt)

    future_dates.sort()
    return [d.strftime("%Y%m%d") for d in future_dates]


def _is_third_friday(dt: datetime) -> bool:
    return dt.weekday() == 4 and 15 <= dt.day <= 21


def _is_weekly(dt: datetime) -> bool:
    return dt.weekday() == 4 and not _is_third_friday(dt)


def extract_weeklies(expirations: list[str], count: int = 4) -> list[str]:
    """Return the next ``count`` weekly expiries from ``expirations``."""

    fridays = []
    for exp in filter_future_expiries(expirations):
        dt = datetime.strptime(exp, "%Y%m%d")
        if _is_weekly(dt):
            fridays.append(exp)
        if len(fridays) == count:
            break
    return fridays


def extract_monthlies(expirations: list[str], count: int = 3) -> list[str]:
    """Return the next ``count`` third-Friday expiries from ``expirations``."""

    months = []
    for exp in filter_future_expiries(expirations):
        dt = datetime.strptime(exp, "%Y%m%d")
        if _is_third_friday(dt):
            months.append(exp)
        if len(months) == count:
            break
    return months


def today() -> date:
    """Return ``TOMIC_TODAY`` or today's date."""

    env = os.getenv("TOMIC_TODAY")
    if env:
        return datetime.strptime(env, "%Y-%m-%d").date()
    return date.today()


def select_near_atm(
    strikes: list[float],
    expiries: list[str],
    spot_price: float | None,
    *,
    width: int = 10,
    count: int = 4,
) -> tuple[list[str], list[float]]:
    """Return the first ``count`` expiries and strikes near ``spot_price``.

    Strikes are included when their rounded value is within ``width`` points of
    ``round(spot_price)``. This mirrors the subset used in
    :func:`fetch_single_option.run`.
    """

    center = round(spot_price or 0)
    sel_strikes = [s for s in strikes if abs(round(s) - center) <= width]
    return expiries[:count], sel_strikes


def latest_close_date(symbol: str) -> str | None:
    """Return the most recent close date for ``symbol`` from price history."""

    base = Path(cfg_get("PRICE_HISTORY_DIR", "tomic/data/spot_prices"))
    path = base / f"{symbol}.json"
    data = load_json(path)
    if isinstance(data, list) and data:
        data.sort(key=lambda r: r.get("date", ""))
        return str(data[-1].get("date"))
    return None


def get_option_mid_price(option: dict) -> float | None:
    """Return midpoint price for ``option`` or close price as fallback."""

    try:
        bid = float(option.get("bid"))
        ask = float(option.get("ask"))
        if bid > 0 and ask > 0:
            return (bid + ask) / 2
    except Exception:
        pass
    close = option.get("close")
    try:
        return float(close) if close is not None else None
    except Exception:
        return None
