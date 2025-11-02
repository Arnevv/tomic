import os
import socket
import sys
import threading
import time
from typing import Any, Dict

from ibapi.client import EClient
from ibapi.wrapper import EWrapper

from tomic.config import get as cfg_get

from tomic.logutils import logger, log_result
from .client_registry import ACTIVE_CLIENT_IDS

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
        self._contract_details_lock = threading.Lock()
        self._contract_details_requests: Dict[int, Dict[str, Any]] = {}
        self._snapshot_lock = threading.Lock()
        self._snapshot_requests: Dict[int, Dict[str, Any]] = {}

    def nextValidId(self, orderId: int) -> None:  # noqa: N802 - IB API callback
        self.next_valid_id = orderId
        logger.debug(f"IB nextValidId -> {orderId}")

    def _next_request_id(self) -> int:
        with self._req_lock:
            req_id = self._next_req_id
            self._next_req_id += 1
            return req_id

    def contractDetails(self, reqId: int, contractDetails) -> None:  # noqa: N802 - IB API
        with self._contract_details_lock:
            state = self._contract_details_requests.get(reqId)
            if state is not None:
                state.setdefault("details", []).append(contractDetails)

    def contractDetailsEnd(self, reqId: int) -> None:  # noqa: N802 - IB API
        with self._contract_details_lock:
            state = self._contract_details_requests.get(reqId)
            if state is not None:
                state.setdefault("event", threading.Event()).set()

    def tickPrice(self, reqId: int, tickType: int, price: float, attrib) -> None:  # noqa: N802
        with self._snapshot_lock:
            state = self._snapshot_requests.get(reqId)
            if state is None:
                return
            try:
                state.setdefault("ticks", {})[int(tickType)] = float(price)
            except (TypeError, ValueError):
                return

    def tickSnapshotEnd(self, reqId: int) -> None:  # noqa: N802
        with self._snapshot_lock:
            state = self._snapshot_requests.get(reqId)
            if state is not None:
                state.setdefault("event", threading.Event()).set()

    def get_contract_details(self, contract: Any, timeout_ms: int | None = None) -> Any:
        timeout_ms = 2000 if timeout_ms is None else max(int(timeout_ms), 1)
        state: Dict[str, Any] = {
            "event": threading.Event(),
            "details": [],
            "error": None,
        }
        req_id = self._next_request_id()
        with self._contract_details_lock:
            self._contract_details_requests[req_id] = state
        try:
            self.reqContractDetails(req_id, contract)
            timeout = max(timeout_ms / 1000.0, 0.5)
            if not state["event"].wait(timeout):
                raise TimeoutError("contract details timeout")
            error = state.get("error")
            if error:
                raise RuntimeError(error)
            details = state.get("details")
            if isinstance(details, list) and details:
                return details[0]
            return None
        finally:
            try:
                self.cancelContractDetails(req_id)
            except Exception:
                pass
            with self._contract_details_lock:
                self._contract_details_requests.pop(req_id, None)

    def request_snapshot_with_mdtype(
        self, contract: Any, md_type: int, timeout_ms: int
    ) -> Dict[int, float]:
        timeout_ms = max(int(timeout_ms), 1)
        state: Dict[str, Any] = {
            "event": threading.Event(),
            "ticks": {},
            "error": None,
        }
        req_id = self._next_request_id()
        with self._snapshot_lock:
            self._snapshot_requests[req_id] = state
        try:
            try:
                self.reqMarketDataType(md_type)
            except Exception:
                pass
            self.reqMktData(req_id, contract, "", True, False, [])
            timeout = max(timeout_ms / 1000.0, 0.5)
            if not state["event"].wait(timeout):
                raise TimeoutError("snapshot timeout")
            error = state.get("error")
            if error:
                raise RuntimeError(error)
            ticks = state.get("ticks", {})
            return {int(k): float(v) for k, v in ticks.items()}
        finally:
            try:
                self.cancelMktData(req_id)
            except Exception:
                pass
            with self._snapshot_lock:
                self._snapshot_requests.pop(req_id, None)

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

        message = f"IB error {errorCode}: {errorString}"
        handled = False
        if reqId != -1:
            with self._snapshot_lock:
                state = self._snapshot_requests.get(reqId)
                if state is not None:
                    state["error"] = message
                    state["event"].set()
                    handled = True
            with self._contract_details_lock:
                state = self._contract_details_requests.get(reqId)
                if state is not None:
                    state["error"] = message
                    state["event"].set()
                    handled = True
        logger.error(message)
        if extra:
            logger.error(f"IB extra info: {extra}")
        if handled:
            logger.debug(f"Handled IB error for request {reqId}")


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
