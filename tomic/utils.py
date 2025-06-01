import os
from datetime import datetime, timezone, date


def _is_third_friday(dt: datetime) -> bool:
    return dt.weekday() == 4 and 15 <= dt.day <= 21


def _is_weekly(dt: datetime) -> bool:
    return dt.weekday() == 4 and not _is_third_friday(dt)


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


def today() -> date:
    """Return TOMIC_TODAY or today's UTC date."""
    env = os.getenv("TOMIC_TODAY")
    return (
        datetime.strptime(env, "%Y-%m-%d").date()
        if env
        else datetime.now(timezone.utc).date()
    )
