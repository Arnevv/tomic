"""Utility functions for market data clients.

This module contains standalone helper functions extracted from market_client.py
to improve code organization and reduce module size.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

try:  # pragma: no cover - optional dependency during tests
    from ibapi.utils import floatMaxString
except Exception:  # pragma: no cover - tests provide stub

    def floatMaxString(val: float) -> str:  # type: ignore[misc]
        return str(val)


if TYPE_CHECKING:
    from datetime import tzinfo

# Descriptions for Interactive Brokers market data types
DATA_TYPE_DESCRIPTIONS: dict[int, str] = {
    1: "realtime",
    2: "frozen",
    3: "delayed",
    4: "delayed frozen",
}


def contract_repr(contract) -> str:
    """Return a human-readable representation of an IB contract."""
    return (
        f"{contract.secType} {contract.symbol} "
        f"{contract.lastTradeDateOrContractMonth or ''} "
        f"{contract.right or ''}{floatMaxString(contract.strike)} "
        f"{contract.exchange or ''} {contract.currency or ''} "
        f"(conId={getattr(contract, 'conId', None)})"
    ).strip()


def is_market_open(trading_hours: str, now: datetime, tz: "tzinfo | None" = None) -> bool:
    """Return ``True`` if ``now`` falls within ``trading_hours``.

    ``trading_hours`` should contain **regular** trading sessions only. If a
    string with extended hours is provided, ensure it has been filtered to
    regular hours first.

    Parameters
    ----------
    trading_hours:
        IB-formatted trading hours string (e.g. "20231201:0930-1600;20231202:CLOSED")
    now:
        Current datetime to check
    tz:
        Timezone for parsing, defaults to ``now.tzinfo``
    """

    tz = tz or now.tzinfo
    day = now.strftime("%Y%m%d")
    for part in trading_hours.split(";"):
        if ":" not in part:
            continue
        date_part, hours_part = part.split(":", 1)
        if date_part != day:
            continue
        if hours_part == "CLOSED":
            return False
        for session in hours_part.split(","):
            try:
                start_str, end_str = session.split("-")
            except ValueError:
                continue
            # remove any appended date information (e.g. "1700-0611:2000")
            start_str = start_str.split(":")[-1][:4]
            end_str = end_str.split(":")[0][:4]
            start_dt = datetime.strptime(day + start_str, "%Y%m%d%H%M").replace(tzinfo=tz)
            end_dt = datetime.strptime(day + end_str, "%Y%m%d%H%M").replace(tzinfo=tz)
            # handle sessions that cross midnight
            if end_dt <= start_dt:
                end_dt += timedelta(days=1)
            if start_dt <= now <= end_dt:
                return True
        return False
    return False


def market_hours_today(
    trading_hours: str, now: datetime, tz: "tzinfo | None" = None
) -> tuple[str, str] | None:
    """Return the market open and close time (HH:MM) for ``now``.

    ``trading_hours`` should represent regular trading hours. The function
    returns ``None`` if the market is closed or no session matches ``now``'s
    date.

    Parameters
    ----------
    trading_hours:
        IB-formatted trading hours string
    now:
        Current datetime to check
    tz:
        Timezone for parsing, defaults to ``now.tzinfo``
    """

    tz = tz or now.tzinfo
    day = now.strftime("%Y%m%d")
    for part in trading_hours.split(";"):
        if ":" not in part:
            continue
        date_part, hours_part = part.split(":", 1)
        if date_part != day:
            continue
        if hours_part == "CLOSED":
            return None
        session = hours_part.split(",")[0]
        try:
            start_str, end_str = session.split("-")
        except ValueError:
            return None
        start_str = start_str.split(":")[-1][:4]
        end_str = end_str.split(":")[0][:4]
        start_dt = datetime.strptime(day + start_str, "%Y%m%d%H%M").replace(tzinfo=tz)
        end_dt = datetime.strptime(day + end_str, "%Y%m%d%H%M").replace(tzinfo=tz)
        if end_dt <= start_dt:
            end_dt += timedelta(days=1)
        return start_dt.strftime("%H:%M"), end_dt.strftime("%H:%M")
    return None


__all__ = [
    "DATA_TYPE_DESCRIPTIONS",
    "contract_repr",
    "is_market_open",
    "market_hours_today",
]
