from __future__ import annotations

from datetime import datetime
from types import MethodType
import threading

from ibapi.contract import Contract

from .ib_connection import connect_ib
from tomic.logutils import logger


def _contract_repr(contract: Contract) -> str:
    """Return a simple representation of ``contract`` for logging."""
    return (
        f"{getattr(contract, 'symbol', '')} "
        f"{getattr(contract, 'lastTradeDateOrContractMonth', '')} "
        f"{getattr(contract, 'strike', '')} "
        f"{getattr(contract, 'right', '')}"
    ).strip()


def fetch_historical_iv(contract: Contract) -> float | None:
    """Return the last implied volatility for ``contract`` using historical data."""

    # Use a unique client ID to avoid clashes with existing connections. When
    # running tests, ``connect_ib`` may be patched with a simple stub that does
    # not accept the ``unique`` keyword, so fall back gracefully if needed.
    try:
        app = connect_ib(unique=True)
    except TypeError:
        app = connect_ib()
    except Exception as exc:  # pragma: no cover - safety for missing stub
        logger.debug(
            "connect_ib failed for %s: %s", _contract_repr(contract), exc
        )
        return None
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

    orig_error = app.error

    def hist_error(
        self,
        reqId: int,
        errorCode: int = None,
        errorString: str = None,
        errorTime: int | None = None,
        advancedOrderRejectJson: str | None = None,
    ) -> None:
        if errorCode in (200, 162):
            logger.debug(
                "reqHistoricalData error %s for %s: %s",
                errorCode,
                _contract_repr(contract),
                errorString,
            )
        orig_error(reqId, errorCode, errorString, errorTime, advancedOrderRejectJson)

    app.error = MethodType(hist_error, app)

    query_time = datetime.now().strftime("%Y%m%d-%H:%M:%S")
    logger.debug(
        "reqHistoricalData sent: reqId=1, contract=%s, query_time=%s, duration=1 D, barSize=1 day, what=OPTION_IMPLIED_VOLATILITY",
        _contract_repr(contract),
        query_time,
    )
    try:
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
    except Exception as exc:  # pragma: no cover - safety for missing stub
        logger.debug(
            "reqHistoricalData failed for %s: %s",
            _contract_repr(contract),
            exc,
        )
    finally:
        try:
            app.disconnect()
        except Exception:
            pass
    return iv


__all__ = ["fetch_historical_iv"]
