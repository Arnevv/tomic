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


def fetch_historical_option_data(
    contracts: dict[int, Contract], *, app=None, what: str = "TRADES"
) -> dict[int, dict[str, float | None]]:
    """Return last IV and close price for provided contracts.

    When ``app`` is ``None`` a temporary IB connection is opened.  When an
    existing client instance is provided it will be reused and callbacks are
    restored afterwards.
    """

    own_client = False
    if app is None:
        try:
            app = connect_ib(unique=True)
        except TypeError:
            app = connect_ib()
        except Exception as exc:  # pragma: no cover - safety for missing stub
            logger.debug("connect_ib failed for bulk request: %s", exc)
            return {rid: {"iv": None, "close": None} for rid in contracts}
        own_client = True

    results: dict[int, dict[str, float | None]] = {
        rid: {"iv": None, "close": None} for rid in contracts
    }
    req_map: dict[int, tuple[int, str, Contract]] = {}
    pending: set[int] = set()
    done = threading.Event()
    lock = threading.Lock()

    orig_hist = getattr(app, "historicalData", None)
    orig_end = getattr(app, "historicalDataEnd", None)
    orig_error = getattr(app, "error", None)

    def hist(self, reqId: int, bar) -> None:  # noqa: N802 - IB callback
        with lock:
            info = req_map.get(reqId)
            if info:
                rid, key, _ = info
                logger.debug(
                    "\ud83d\udce5 historicalData callback: reqId=%s, bar=%s",
                    reqId,
                    vars(bar),
                )
                if getattr(bar, "close", None) not in (None, -1):
                    results[rid][key] = bar.close
        if orig_hist:
            orig_hist(reqId, bar)

    def hist_end(self, reqId: int, start: str, end: str) -> None:  # noqa: N802
        with lock:
            pending.discard(reqId)
            if not pending:
                done.set()
        if orig_end:
            orig_end(reqId, start, end)

    app.historicalData = MethodType(hist, app)
    app.historicalDataEnd = MethodType(hist_end, app)

    def hist_error(
        self,
        reqId: int,
        errorCode: int = None,
        errorString: str = None,
        errorTime: int | None = None,
        advancedOrderRejectJson: str | None = None,
    ) -> None:
        info = req_map.get(reqId)
        con = info[2] if info else None
        if errorCode in (200, 162) and con:
            logger.debug(
                "reqHistoricalData error %s for %s: %s",
                errorCode,
                _contract_repr(con),
                errorString,
            )
        if orig_error:
            orig_error(reqId, errorCode, errorString, errorTime, advancedOrderRejectJson)

    app.error = MethodType(hist_error, app)

    query_time = datetime.now().strftime("%Y%m%d-%H:%M:%S")
    next_id = 1
    for rid, contract in contracts.items():
        iv_id = next_id
        next_id += 1
        close_id = next_id
        next_id += 1
        req_map[iv_id] = (rid, "iv", contract)
        req_map[close_id] = (rid, "close", contract)
        pending.add(iv_id)
        pending.add(close_id)
        logger.debug(
            "reqHistoricalData sent: reqId=%s, contract=%s, query_time=%s, duration=1 D, barSize=1 day, what=%s",
            iv_id,
            _contract_repr(contract),
            query_time,
            "OPTION_IMPLIED_VOLATILITY",
        )
        logger.debug(
            "\ud83d\udce4 reqHistoricalData raw params: useRTH=%s, includeExpired=%s, whatToShow=%s, conId=%s, primaryExchange=%s",
            0,
            getattr(contract, "includeExpired", None),
            "OPTION_IMPLIED_VOLATILITY",
            getattr(contract, "conId", None),
            getattr(contract, "primaryExchange", None),
        )
        logger.debug(contract.__dict__)
        app.reqHistoricalData(
            iv_id,
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
        logger.debug(
            "reqHistoricalData sent: reqId=%s, contract=%s, query_time=%s, duration=1 D, barSize=1 day, what=%s",
            close_id,
            _contract_repr(contract),
            query_time,
            what,
        )
        logger.debug(
            "\ud83d\udce4 reqHistoricalData raw params: useRTH=%s, includeExpired=%s, whatToShow=%s, conId=%s, primaryExchange=%s",
            0,
            getattr(contract, "includeExpired", None),
            what,
            getattr(contract, "conId", None),
            getattr(contract, "primaryExchange", None),
        )
        logger.debug(contract.__dict__)
        app.reqHistoricalData(
            close_id,
            contract,
            query_time,
            "1 D",
            "1 day",
            what,
            0,
            1,
            False,
            [],
        )

    done.wait(60)

    if own_client:
        try:
            app.disconnect()
        except Exception:
            pass
    else:
        if orig_hist is not None:
            app.historicalData = orig_hist
        if orig_end is not None:
            app.historicalDataEnd = orig_end
        if orig_error is not None:
            app.error = orig_error

    return results


def fetch_historical_iv(contract: Contract) -> float | None:
    """Return the last implied volatility for ``contract`` using historical data."""

    res = fetch_historical_option_data({1: contract})
    return res.get(1, {}).get("iv")


__all__ = ["fetch_historical_iv", "fetch_historical_option_data"]
