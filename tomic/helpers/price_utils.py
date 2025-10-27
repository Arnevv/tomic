from __future__ import annotations
"""Price-related helper utilities."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from tomic.config import get as cfg_get  # re-exported for monkeypatching in tests
from tomic.helpers.price_meta import load_price_meta
from tomic.journal.utils import load_json
from tomic.logutils import logger
from tomic.utils import load_price_history


@dataclass(frozen=True)
class ClosePriceSnapshot:
    """Container describing the latest close price and its metadata."""

    price: float | None
    date: str | None
    source: str | None = None
    fetched_at: str | None = None
    baseline: bool = False

    def __iter__(self) -> Iterator[Any]:
        yield self.price
        yield self.date

    def __len__(self) -> int:  # pragma: no cover - structural helper
        return 2

    def __getitem__(self, index: int) -> Any:  # pragma: no cover - structural helper
        if index == 0:
            return self.price
        if index == 1:
            return self.date
        raise IndexError("ClosePriceSnapshot only exposes price and date")


def _load_latest_close(
    symbol: str, *, return_date_only: bool = False
) -> ClosePriceSnapshot | str | None:
    """Return the most recent close and its date for ``symbol``.

    Parameters
    ----------
    symbol:
        The ticker symbol to look up.
    return_date_only:
        When ``True`` only the close date is returned.  Otherwise a tuple of
        ``(price, date)`` is returned as before.
    """

    logger.debug(f"Loading close price for {symbol}")
    data = load_price_history(symbol)
    if not data:
        base = cfg_get("PRICE_HISTORY_DIR")
        if base:
            path = Path(base) / f"{symbol}.json"
            try:
                raw = load_json(path)
            except Exception:
                raw = None
            if isinstance(raw, list):
                raw.sort(key=lambda rec: rec.get("date", ""))
                data = raw
    meta_source: str | None = None
    fetched_at: str | None = None
    baseline_active = False
    baseline_as_of: str | None = None

    try:
        meta = load_price_meta()
    except Exception:  # pragma: no cover - defensive I/O guard
        meta = {}
    entry = meta.get(symbol.upper())
    if isinstance(entry, dict):
        meta_source = entry.get("source") or None
        fetched_at = entry.get("fetched_at") or None
        baseline_active = bool(entry.get("baseline_active"))
        raw_as_of = entry.get("baseline_as_of")
        if isinstance(raw_as_of, str):
            baseline_as_of = raw_as_of

    if data:
        rec = data[-1]
        try:
            price = float(rec.get("close"))
            date_str = str(rec.get("date"))
        except Exception:
            price = None
            date_str = None
        if date_str:
            is_baseline = bool(baseline_active and baseline_as_of == date_str)
        else:
            is_baseline = False

        if price is not None:
            try:
                if price <= 0:
                    logger.debug(
                        f"Ignoring non-positive close for {symbol} on {date_str}: {price}"
                    )
                    snapshot = ClosePriceSnapshot(
                        None, date_str, meta_source, fetched_at, False
                    )
                    return date_str if return_date_only else snapshot
            except Exception:
                price = None

        if price is not None and price > 0 and date_str:
            logger.debug(f"Using last close for {symbol} on {date_str}: {price}")
            snapshot = ClosePriceSnapshot(
                float(price), date_str, meta_source, fetched_at, is_baseline
            )
            return snapshot.date if return_date_only else snapshot

        snapshot = ClosePriceSnapshot(None, date_str, meta_source, fetched_at, False)
        return snapshot.date if return_date_only else snapshot

    snapshot = ClosePriceSnapshot(None, None, meta_source, fetched_at, False)
    return snapshot.date if return_date_only else snapshot


__all__ = ["ClosePriceSnapshot", "_load_latest_close"]
