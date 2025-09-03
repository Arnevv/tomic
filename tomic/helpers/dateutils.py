from datetime import datetime, date
from typing import Optional, Union

from tomic.utils import today


DateLike = Union[str, date]


def parse_date(d: DateLike) -> Optional[date]:
    """Return ``d`` parsed as :class:`datetime.date`.

    Accepts strings in ``YYYYMMDD`` or ``YYYY-MM-DD`` format or ``date`` objects.
    """
    if isinstance(d, date):
        return d
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(d), fmt).date()
        except Exception:
            continue
    return None


def dte_between_dates(start: DateLike, end: DateLike) -> Optional[int]:
    """Return days between ``start`` and ``end``."""
    s = parse_date(start)
    e = parse_date(end)
    if s is None:
        s = today()
    if s is None or e is None:
        return None
    return (e - s).days

