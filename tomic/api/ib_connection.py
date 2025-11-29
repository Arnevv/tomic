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
        import time as _time
        _t_start = _time.perf_counter()
        client_id = getattr(self, "clientId", None)
        was_connected = self.isConnected() if hasattr(self, "isConnected") else None
        logger.info(
            "[IBClient.disconnect] Starting disconnect: client_id=%s, was_connected=%s, active_ids=%s",
            client_id, was_connected, list(ACTIVE_CLIENT_IDS),
        )
        try:
            super().disconnect()
            _t_done = _time.perf_counter()
            logger.info(
                "[IBClient.disconnect] super().disconnect() completed in %.0fms",
                (_t_done - _t_start) * 1000,
            )
        except Exception as e:
            _t_error = _time.perf_counter()
            logger.warning(
                "[IBClient.disconnect] Error during disconnect after %.0fms: %s",
                (_t_error - _t_start) * 1000, e,
            )
        finally:
            if client_id is not None:
                ACTIVE_CLIENT_IDS.discard(client_id)
                logger.info(
                    "[IBClient.disconnect] Removed client_id=%d from registry, active_ids now: %s",
                    client_id, list(ACTIVE_CLIENT_IDS),
                )

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
        # Known TWS connection-related error codes
        CONNECTION_ERROR_CODES = {
            502: "Could not connect to TWS - is it running?",
            504: "Not connected to TWS",
            507: "Bad Message Length (connection issue)",
            509: "Exception caught while reading socket",
            1100: "Connectivity lost",
            1101: "Connectivity restored - data lost",
            1102: "Connectivity restored - data maintained",
            2103: "Market data farm connection broken",
            2104: "Market data farm connection OK",
            2105: "Historical data farm connection broken",
            2106: "Historical data farm connection OK",
            2110: "Connectivity between TWS and server is broken",
            2157: "Security definition server connection OK",
            2158: "Security definition server connection broken",
        }

        # Log connection-related errors prominently
        if errorCode in CONNECTION_ERROR_CODES:
            client_id = getattr(self, "clientId", None)
            logger.warning(
                "[IB CONNECTION] code=%d client_id=%s: %s (%s)",
                errorCode, client_id, errorString, CONNECTION_ERROR_CODES[errorCode],
            )

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
    import time as _time
    _t_start = _time.perf_counter()

    if unique:
        client_id = int(time.time() * 1000) % 2_000_000
    elif client_id is None:
        client_id = int(cfg_get("IB_CLIENT_ID", 100))

    # Log registry status before connection attempt
    logger.info(
        "[connect_ib] PRE-CONNECT: client_id=%d, active_ids=%s, count=%d",
        client_id,
        list(ACTIVE_CLIENT_IDS) if len(ACTIVE_CLIENT_IDS) <= 5 else f"({len(ACTIVE_CLIENT_IDS)} ids)",
        len(ACTIVE_CLIENT_IDS),
    )

    if client_id in ACTIVE_CLIENT_IDS:
        logger.warning(
            "[connect_ib] ⚠️ CONFLICT: client_id %d already in ACTIVE_CLIENT_IDS! "
            "This may cause TWS to reject the connection.",
            client_id,
        )
    if app is None:
        app = IBClient()
    elif not isinstance(app, IBClient):  # pragma: no cover - defensive
        raise TypeError("app must inherit from IBClient")

    _t_pre_connect = _time.perf_counter()
    logger.info(
        "[connect_ib] SOCKET CONNECT starting: host=%s port=%d client_id=%d",
        host, port, client_id,
    )
    try:
        app.connect(host, port, client_id)
        _t_post_connect = _time.perf_counter()
        logger.info(
            "[connect_ib] SOCKET CONNECT done in %.0fms, isConnected=%s",
            (_t_post_connect - _t_pre_connect) * 1000,
            app.isConnected() if hasattr(app, "isConnected") else "unknown",
        )
        ACTIVE_CLIENT_IDS.add(client_id)
        logger.info(
            "[connect_ib] Added client_id=%d to registry, active_ids now: %s",
            client_id, list(ACTIVE_CLIENT_IDS),
        )
    except socket.error as e:
        _t_error = _time.perf_counter()
        logger.error(
            "[connect_ib] SOCKET ERROR after %.0fms: %s",
            (_t_error - _t_pre_connect) * 1000, e,
        )
        raise RuntimeError(f"❌ Kon niet verbinden met TWS op {host}:{port}: {e}")

    _t_pre_thread = _time.perf_counter()
    logger.info("[connect_ib] Starting message loop thread...")
    thread = threading.Thread(target=app.run, daemon=True)
    thread.start()
    app._thread = thread
    logger.info("[connect_ib] Message loop thread started (daemon=True)")

    logger.info("[connect_ib] Waiting for nextValidId (timeout=%ds)...", timeout)
    start = time.time()
    wait_count = 0
    while app.next_valid_id is None:
        elapsed = time.time() - start
        if elapsed > timeout:
            logger.error(
                "[connect_ib] TIMEOUT waiting for nextValidId after %.1fs "
                "(waited %d iterations), isConnected=%s, active_ids=%s",
                elapsed, wait_count,
                app.isConnected() if hasattr(app, "isConnected") else "unknown",
                list(ACTIVE_CLIENT_IDS),
            )
            # Clean up on timeout
            try:
                ACTIVE_CLIENT_IDS.discard(client_id)
                app.disconnect()
            except Exception:
                pass
            raise TimeoutError("⏱ Timeout bij wachten op nextValidId")
        time.sleep(0.1)
        wait_count += 1
        if wait_count % 10 == 0:  # Log every second
            logger.info(
                "[connect_ib] Still waiting for nextValidId... (%.1fs elapsed, isConnected=%s)",
                elapsed,
                app.isConnected() if hasattr(app, "isConnected") else "unknown",
            )

    _t_done = _time.perf_counter()
    logger.info(
        "[connect_ib] SUCCESS: nextValidId=%d, total_time=%.0fms, active_ids=%s",
        app.next_valid_id,
        (_t_done - _t_start) * 1000,
        list(ACTIVE_CLIENT_IDS),
    )
    return app


def diagnose_tws_connection(
    host: str = "127.0.0.1",
    port: int = 7497,
    timeout: float = 5.0,
) -> dict:
    """Diagnose TWS connection issues without actually connecting.

    Returns a diagnostic report with:
    - socket_reachable: Can we open a socket to TWS?
    - active_client_ids: Currently registered client IDs
    - tws_responsive: Did TWS respond to the socket connection?

    Usage:
        from tomic.api.ib_connection import diagnose_tws_connection
        report = diagnose_tws_connection()
        print(report)
    """
    import socket as sock
    report = {
        "host": host,
        "port": port,
        "socket_reachable": False,
        "socket_error": None,
        "active_client_ids": list(ACTIVE_CLIENT_IDS),
        "active_count": len(ACTIVE_CLIENT_IDS),
        "tws_responsive": False,
        "connection_time_ms": None,
    }

    logger.info("[diagnose_tws] Starting TWS connection diagnosis...")
    logger.info("[diagnose_tws] Active client IDs: %s", list(ACTIVE_CLIENT_IDS))

    # Test basic socket connectivity
    start = time.time()
    try:
        test_socket = sock.socket(sock.AF_INET, sock.SOCK_STREAM)
        test_socket.settimeout(timeout)
        test_socket.connect((host, port))
        elapsed = (time.time() - start) * 1000
        report["socket_reachable"] = True
        report["connection_time_ms"] = round(elapsed, 1)

        # Try to receive initial handshake
        try:
            test_socket.settimeout(2.0)
            data = test_socket.recv(1024)
            if data:
                report["tws_responsive"] = True
                logger.info("[diagnose_tws] TWS responded with %d bytes", len(data))
        except sock.timeout:
            logger.warning("[diagnose_tws] TWS did not send initial data (timeout)")
        except Exception as e:
            logger.warning("[diagnose_tws] Error receiving TWS data: %s", e)

        test_socket.close()
        logger.info(
            "[diagnose_tws] Socket connection successful in %.1fms, TWS responsive: %s",
            elapsed, report["tws_responsive"],
        )
    except sock.timeout:
        report["socket_error"] = f"Connection timeout after {timeout}s"
        logger.error("[diagnose_tws] Socket timeout - TWS may not be running")
    except sock.error as e:
        report["socket_error"] = str(e)
        logger.error("[diagnose_tws] Socket error: %s", e)
    except Exception as e:
        report["socket_error"] = str(e)
        logger.error("[diagnose_tws] Unexpected error: %s", e)

    # Check for potential conflicts
    if report["active_count"] > 0:
        logger.warning(
            "[diagnose_tws] WARNING: %d client ID(s) already registered: %s",
            report["active_count"], report["active_client_ids"],
        )
        logger.warning(
            "[diagnose_tws] This may indicate zombie connections or concurrent usage"
        )

    return report


def clear_stale_client_ids() -> list[int]:
    """Clear all client IDs from the registry.

    This is useful when you suspect zombie connections are blocking new connections.
    Returns the list of cleared client IDs.

    Usage:
        from tomic.api.ib_connection import clear_stale_client_ids
        cleared = clear_stale_client_ids()
        print(f"Cleared {len(cleared)} stale client IDs")
    """
    cleared = list(ACTIVE_CLIENT_IDS)
    if cleared:
        logger.warning(
            "[clear_stale_client_ids] Clearing %d client IDs: %s",
            len(cleared), cleared,
        )
        ACTIVE_CLIENT_IDS.clear()
    else:
        logger.info("[clear_stale_client_ids] No client IDs to clear")
    return cleared
