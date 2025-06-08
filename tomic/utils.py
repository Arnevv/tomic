import os
from datetime import datetime, timezone, date


def _is_third_friday(dt: datetime) -> bool:
    """Return ``True`` for the 3rd Friday of the month."""

    return dt.weekday() == 4 and 15 <= dt.day <= 21


def _is_weekly(dt: datetime) -> bool:
    """Return ``True`` for standard weekly expiries."""

    return dt.weekday() in {0, 2, 4} and not _is_third_friday(dt)


def extract_weeklies(expirations: list[str], count: int = 4) -> list[str]:
    """Return the next ``count`` weekly expiries from ``expirations``."""

    weeks = []
    for exp in sorted(expirations):
        try:
            dt = datetime.strptime(exp, "%Y%m%d")
        except Exception:
            continue
        if _is_weekly(dt):
            weeks.append(exp)
        if len(weeks) == count:
            break
    return weeks


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
        if dt.weekday() in {0, 2, 4}:
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
