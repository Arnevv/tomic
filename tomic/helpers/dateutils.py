from bisect import bisect_left
from datetime import datetime, date, timedelta
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


def normalize_earnings_context(
    raw_date: object,
    raw_days: object,
    today_fn: Callable[[], date] | None = None,
) -> tuple[date | None, int | None]:
    """Return normalized earnings date and days-until tuple.

    ``raw_date`` may be a :class:`date`, ISO string or other parseable format.
    ``raw_days`` may be provided as ``int``/``float``/string. When ``raw_days``
    is missing but ``raw_date`` is available the helper computes the delta using
    ``today_fn`` (defaults to :func:`today`).
    """

    today_value = (today_fn or today)()

    earnings_date = parse_date(raw_date) if raw_date is not None else None

    days_until: int | None
    if isinstance(raw_days, (int, float)):
        try:
            days_until = int(raw_days)
        except Exception:  # pragma: no cover - defensive guard
            days_until = None
    elif isinstance(raw_days, str) and raw_days.strip():
        try:
            days_until = int(float(raw_days))
        except Exception:
            days_until = None
    else:
        days_until = None

    if days_until is None and earnings_date is not None:
        try:
            days_until = (earnings_date - today_value).days
        except Exception:  # pragma: no cover - defensive guard
            days_until = None

    if earnings_date is None and days_until is not None:
        try:
            earnings_date = today_value + timedelta(days=days_until)
        except Exception:  # pragma: no cover - defensive guard
            earnings_date = None

    return earnings_date, days_until


def normalize_expiry_code(value: object) -> str:
    """Return numeric expiry code (``YYYYMMDD``) from ``value``."""

    if value is None:
        raise ValueError("expiry value is required")
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if len(digits) == 6:
        digits = "20" + digits
    if len(digits) != 8:
        raise ValueError(f"unsupported expiry format: {value!r}")
    return digits

