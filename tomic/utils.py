import os
from datetime import datetime, date


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
