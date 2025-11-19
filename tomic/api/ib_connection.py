import os
import socket
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ibapi.client import EClient
from ibapi.wrapper import EWrapper

from tomic.config import get as cfg_get

from tomic.logutils import logger, log_result
from .client_registry import ACTIVE_CLIENT_IDS


@dataclass
class RequestState:
    """State for tracking IB API requests."""
    event: threading.Event = field(default_factory=threading.Event)
    result: Any = field(default_factory=list)
    error: Optional[str] = None
    error_code: Optional[int] = None
    started_at: float = field(default_factory=time.monotonic)
    kind: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

PROTOBUF_PATH = os.path.join(os.path.dirname(__file__), "..", "ibapi", "protobuf")
_PROTOBUF_ABS = os.path.abspath(PROTOBUF_PATH)
if _PROTOBUF_ABS not in sys.path:
    sys.path.insert(0, _PROTOBUF_ABS)

class IBClient(EClient, EWrapper):
    def __init__(self) -> None:
        EClient.__init__(self, self)
        self.next_valid_id = None
        self._req_lock = threading.Lock()
        self._next_req_id = 1
        self._requests_lock = threading.RLock()
        self._requests: Dict[int, RequestState] = {}

    def nextValidId(self, orderId: int) -> None:  # noqa: N802 - IB API callback
        self.next_valid_id = orderId
        logger.debug(f"IB nextValidId -> {orderId}")

    def _next_request_id(self) -> int:
        with self._req_lock:
            req_id = self._next_req_id
            self._next_req_id += 1
            return req_id

    def contractDetails(self, reqId: int, contractDetails) -> None:  # noqa: N802 - IB API
        with self._requests_lock:
            state = self._requests.get(reqId)
            if state is not None and state.kind == "contract_details":
                state.result.append(contractDetails)

    def contractDetailsEnd(self, reqId: int) -> None:  # noqa: N802 - IB API
        with self._requests_lock:
            state = self._requests.get(reqId)
            if state is not None and state.kind == "contract_details":
                state.event.set()

    def tickPrice(self, reqId: int, tickType: int, price: float, attrib) -> None:  # noqa: N802
        with self._requests_lock:
            state = self._requests.get(reqId)
            if state is None or state.kind != "snapshot":
                return
            try:
                # Filter sentinel values (-1.0 or <= 0 typically means no data)
                price_val = float(price)
                if price_val <= 0:
                    return
                if not isinstance(state.result, dict):
                    state.result = {}
                state.result[int(tickType)] = price_val
            except (TypeError, ValueError):
                return

    def tickSnapshotEnd(self, reqId: int) -> None:  # noqa: N802
        with self._requests_lock:
            state = self._requests.get(reqId)
            if state is not None and state.kind == "snapshot":
                state.event.set()

    def get_contract_details(self, contract: Any, timeout_ms: int | None = None) -> Any:
        timeout_ms = 2000 if timeout_ms is None else max(int(timeout_ms), 1)

        # Extract contract info for logging
        symbol = getattr(contract, "symbol", "?")
        sec_type = getattr(contract, "secType", "?")

        state = RequestState(
            result=[],
            kind="contract_details",
            meta={"symbol": symbol, "secType": sec_type},
        )
        req_id = self._next_request_id()

        with self._requests_lock:
            self._requests[req_id] = state

        # Log start
        logger.info(f"[IB] start reqId={req_id} kind=contract_details symbol={symbol}")

        try:
            self.reqContractDetails(req_id, contract)
            timeout_sec = max(timeout_ms / 1000.0, 0.5)
            finished = state.event.wait(timeout_sec)

            if not finished:
                duration = time.monotonic() - state.started_at
                logger.warning(
                    f"[IB] timeout reqId={req_id} kind=contract_details "
                    f"symbol={symbol} after={duration:.2f}s"
                )
                raise TimeoutError(f"contract details timeout for {symbol}")

            if state.error is not None:
                logger.error(
                    f"[IB] error reqId={req_id} kind=contract_details "
                    f"symbol={symbol} err={state.error_code}:{state.error}"
                )
                raise RuntimeError(state.error)

            # Success logging
            details = state.result
            duration = time.monotonic() - state.started_at
            logger.info(
                f"[IB] done reqId={req_id} kind=contract_details "
                f"symbol={symbol} details={len(details)} dur={duration:.2f}s"
            )

            # Return first detail or None for backward compatibility
            if isinstance(details, list) and details:
                return details[0]
            return None
        finally:
            try:
                self.cancelContractDetails(req_id)
            except Exception:
                pass
            with self._requests_lock:
                self._requests.pop(req_id, None)

    # Tick type to field name mapping for logging
    _TICK_FIELD_NAMES: Dict[int, str] = {
        1: "bid",
        2: "ask",
        4: "last",
        6: "high",
        7: "low",
        9: "close",
        14: "open",
    }

    def request_snapshot_with_mdtype(
        self, contract: Any, md_type: int, timeout_ms: int
    ) -> Dict[int, float]:
        timeout_ms = max(int(timeout_ms), 1)

        # Extract contract info for logging
        symbol = getattr(contract, "symbol", "?")

        state = RequestState(
            result={},
            kind="snapshot",
            meta={"symbol": symbol, "mdType": md_type},
        )
        req_id = self._next_request_id()

        with self._requests_lock:
            self._requests[req_id] = state

        # Log start
        logger.info(f"[IB] start reqId={req_id} kind=snapshot symbol={symbol} mdType={md_type}")

        try:
            try:
                self.reqMarketDataType(md_type)
            except Exception:
                pass
            self.reqMktData(req_id, contract, "", True, False, [])
            timeout_sec = max(timeout_ms / 1000.0, 0.5)
            finished = state.event.wait(timeout_sec)

            if not finished:
                duration = time.monotonic() - state.started_at
                logger.warning(
                    f"[IB] timeout reqId={req_id} kind=snapshot "
                    f"symbol={symbol} after={duration:.2f}s"
                )
                raise TimeoutError(f"snapshot timeout for {symbol}")

            if state.error is not None:
                logger.error(
                    f"[IB] error reqId={req_id} kind=snapshot "
                    f"symbol={symbol} err={state.error_code}:{state.error}"
                )
                raise RuntimeError(state.error)

            # Success logging with field names
            ticks = state.result if isinstance(state.result, dict) else {}
            duration = time.monotonic() - state.started_at
            field_names = [
                self._TICK_FIELD_NAMES.get(k, str(k))
                for k in sorted(ticks.keys())
            ]
            logger.info(
                f"[IB] done reqId={req_id} kind=snapshot "
                f"symbol={symbol} fields={','.join(field_names) or 'none'} dur={duration:.2f}s"
            )

            return {int(k): float(v) for k, v in ticks.items()}
        finally:
            try:
                self.cancelMktData(req_id)
            except Exception:
                pass
            with self._requests_lock:
                self._requests.pop(req_id, None)

    def disconnect(self) -> None:  # type: ignore[override]
        """Disconnect from IB and update the active client registry."""
        client_id = getattr(self, "clientId", None)
        try:
            super().disconnect()
        finally:
            if client_id is not None:
                ACTIVE_CLIENT_IDS.discard(client_id)

    # Match the signature expected by :class:`ibapi.wrapper.EWrapper` so
    # callbacks from the decoder don't fail if additional arguments are passed.
    def error(
        self,
        reqId: int,
        errorCode: int,
        errorString: str,
        *extra: object,
    ) -> None:  # noqa: N802 - signature compatible with EWrapper
        """Log IB error messages with full context."""

        if reqId != -1:
            with self._requests_lock:
                state = self._requests.get(reqId)
                if state is not None:
                    state.error = errorString
                    state.error_code = errorCode
                    state.event.set()
                    logger.debug(f"[IB] error callback reqId={reqId} handled")
                    return  # Logged by the request handler

        # Global error or unknown reqId
        logger.error(f"IB error {errorCode}: {errorString}")
        if extra:
            logger.debug(f"IB extra info: {extra}")


@log_result
def connect_ib(
    client_id: int | None = None,
    host: str = "127.0.0.1",
    port: int = 7497,
    timeout: int = 5,
    *,
    unique: bool = False,
    app: IBClient | None = None,
) -> IBClient:
    """Connect to IB.

    When ``unique`` is ``True`` a unique ``client_id`` is generated so
    multiple connections can be opened simultaneously without client id
    clashes.
    """
    if unique:
        client_id = int(time.time() * 1000) % 2_000_000
    elif client_id is None:
        client_id = int(cfg_get("IB_CLIENT_ID", 100))

    if client_id in ACTIVE_CLIENT_IDS:
        logger.warning(f"IB client_id {client_id} already active")
    if app is None:
        app = IBClient()
    elif not isinstance(app, IBClient):  # pragma: no cover - defensive
        raise TypeError("app must inherit from IBClient")

    try:
        logger.debug(f"Connecting to IB host={host} port={port} client_id={client_id}")
        app.connect(host, port, client_id)
        ACTIVE_CLIENT_IDS.add(client_id)
    except socket.error as e:
        raise RuntimeError(f"❌ Kon niet verbinden met TWS op {host}:{port}: {e}")

    thread = threading.Thread(target=app.run, daemon=True)
    thread.start()
    app._thread = thread

    start = time.time()
    while app.next_valid_id is None:
        if time.time() - start > timeout:
            raise TimeoutError("⏱ Timeout bij wachten op nextValidId")
        time.sleep(0.1)

    logger.debug("IB connection established")
    return app
