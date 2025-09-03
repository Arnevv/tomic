from datetime import datetime, date
from typing import Optional, Union

from tomic.utils import today


DateLike = Union[str, date]


def _parse(d: DateLike) -> Optional[date]:
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
    s = _parse(start)
    e = _parse(end)
    if s is None:
        s = today()
    if s is None or e is None:
        return None
    return (e - s).days

