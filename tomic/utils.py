import os
from datetime import datetime, timezone, date


def _is_third_friday(dt: datetime) -> bool:
    return dt.weekday() in {4, 5} and 15 <= dt.day <= 21


def _is_weekly(dt: datetime) -> bool:
    return dt.weekday() in {4, 5} and not _is_third_friday(dt)


def extract_weeklies(expirations: list[str], count: int = 4) -> list[str]:
    """Return the next ``count`` weekly expiries from ``expirations``."""

    fridays = []
    for exp in sorted(expirations):
        try:
            dt = datetime.strptime(exp, "%Y%m%d")
        except Exception:
            continue
        if _is_weekly(dt):
            fridays.append(exp)
        if len(fridays) == count:
            break
    return fridays


def split_expiries(expirations: list[str]) -> tuple[list[str], list[str]]:
    """Return the next regular and weekly expiries.

    Parameters
    ----------
    expirations:
        All expiries received from IB in ``YYYYMMDD`` format.

    Returns
    -------
    tuple[list[str], list[str]]
        First three regular expiries followed by the first four weeklies.
    """

    parsed: list[tuple[datetime, str]] = []
    for exp in expirations:
        try:
            dt = datetime.strptime(exp, "%Y%m%d")
        except Exception:
            continue
        if dt.weekday() in {4, 5}:
            parsed.append((dt, exp))

    parsed.sort(key=lambda x: x[0])
    regulars = [exp for dt, exp in parsed if _is_third_friday(dt)][:3]
    weeklies = [exp for dt, exp in parsed if _is_weekly(dt) and exp not in regulars][:4]
    return regulars, weeklies


def today() -> date:
    """Return TOMIC_TODAY or today's UTC date."""
    env = os.getenv("TOMIC_TODAY")
    return (
        datetime.strptime(env, "%Y-%m-%d").date()
        if env
        else datetime.now(timezone.utc).date()
    )
