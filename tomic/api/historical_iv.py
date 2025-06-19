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
    contracts: dict[int, Contract], *, what: str = "TRADES"
) -> dict[int, dict[str, float | None]]:
    """Return last IV and close price for provided contracts."""

    try:
        app = connect_ib(unique=True)
    except TypeError:
        app = connect_ib()
    except Exception as exc:  # pragma: no cover - safety for missing stub
        logger.debug("connect_ib failed for bulk request: %s", exc)
        return {rid: {"iv": None, "close": None} for rid in contracts}

    results: dict[int, dict[str, float | None]] = {
        rid: {"iv": None, "close": None} for rid in contracts
    }
    req_map: dict[int, tuple[int, str, Contract]] = {}
    pending: set[int] = set()
    done = threading.Event()
    lock = threading.Lock()

    def hist(self, reqId: int, bar) -> None:  # noqa: N802 - IB callback
        with lock:
            info = req_map.get(reqId)
            if not info:
                return
            rid, key, con = info
            if getattr(bar, "close", None) not in (None, -1):
                results[rid][key] = bar.close

    def hist_end(self, reqId: int, start: str, end: str) -> None:  # noqa: N802
        with lock:
            pending.discard(reqId)
            if not pending:
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
        info = req_map.get(reqId)
        con = info[2] if info else None
        if errorCode in (200, 162) and con:
            logger.debug(
                "reqHistoricalData error %s for %s: %s",
                errorCode,
                _contract_repr(con),
                errorString,
            )
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
            "reqHistoricalData sent: reqId=%s, contract=%s, query_time=%s, duration=1 D, barSize=1 day, what=OPTION_IMPLIED_VOLATILITY",
            iv_id,
            _contract_repr(contract),
            query_time,
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

    try:
        app.disconnect()
    except Exception:
        pass

    return results


def fetch_historical_iv(contract: Contract) -> float | None:
    """Return the last implied volatility for ``contract`` using historical data."""

    res = fetch_historical_option_data({1: contract})
    return res.get(1, {}).get("iv")


__all__ = ["fetch_historical_iv", "fetch_historical_option_data"]
