from bisect import bisect_left
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


def is_iso_date(value: str) -> bool:
    """Return ``True`` when ``value`` is a valid ISO ``YYYY-MM-DD`` string."""

    if not isinstance(value, str) or len(value) != 10:
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def to_iso_date(value: DateLike) -> Optional[str]:
    """Return ``value`` normalised to ISO format (``YYYY-MM-DD``)."""

    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if is_iso_date(text):
            return text
        for fmt in ("%m/%d/%Y", "%Y/%m/%d", "%Y%m%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(text, fmt).date().isoformat()
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(text).date().isoformat()
        except ValueError:
            return None
    return None


def insert_chrono(dates: List[str], new_date: str) -> List[str]:
    """Return ``dates`` with ``new_date`` inserted while keeping chronological order."""

    if not is_iso_date(new_date):
        raise ValueError("new_date must be ISO formatted (YYYY-MM-DD)")

    clone = list(dates)
    idx = bisect_left(clone, new_date)
    clone.insert(idx, new_date)
    return clone


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

