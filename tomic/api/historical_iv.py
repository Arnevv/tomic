from __future__ import annotations

from datetime import datetime
from types import MethodType
import threading

from ibapi.contract import Contract

from .ib_connection import connect_ib


def fetch_historical_iv(contract: Contract) -> float | None:
    """Return the last implied volatility for ``contract`` using historical data."""

    app = connect_ib()
    iv: float | None = None
    done = threading.Event()

    def hist(self, reqId: int, bar) -> None:  # noqa: N802 - IB callback
        nonlocal iv
        if getattr(bar, "close", None) not in (None, -1):
            iv = bar.close

    def hist_end(self, reqId: int, start: str, end: str) -> None:  # noqa: N802
        done.set()

    app.historicalData = MethodType(hist, app)
    app.historicalDataEnd = MethodType(hist_end, app)

    query_time = datetime.now().strftime("%Y%m%d-%H:%M:%S")
    app.reqHistoricalData(
        1,
        contract,
        query_time,
        "1 D",
        "1 day",
        "OPTION_IMPLIED_VOLATILITY",
        0,
        1,
        False,
        [],
    )
    done.wait(10)
    app.disconnect()
    return iv


__all__ = ["fetch_historical_iv"]
