from datetime import datetime, date
from typing import Callable, Iterable, List, Optional, Tuple, TypeVar, Union

from tomic.utils import today


DateLike = Union[str, date]
T = TypeVar("T")


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


def filter_by_dte(
    iterable: Iterable[T],
    key_func: Callable[[T], DateLike],
    dte_range: Tuple[int, int],
) -> List[T]:
    """Return items from ``iterable`` with DTE within ``dte_range``."""

    min_dte, max_dte = dte_range
    today_date = today()
    selected: List[T] = []
    for item in iterable:
        d = dte_between_dates(today_date, key_func(item))
        if d is not None and min_dte <= d <= max_dte:
            selected.append(item)
    return selected

