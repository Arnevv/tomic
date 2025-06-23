import threading
import time
import socket
from ibapi.client import EClient
from ibapi.wrapper import EWrapper

import sys
import os

from tomic.config import get as cfg_get

from tomic.logutils import logger, log_result

PROTOBUF_PATH = os.path.join(os.path.dirname(__file__), "..", "ibapi", "protobuf")
sys.path.insert(0, os.path.abspath(PROTOBUF_PATH))

class IBClient(EClient, EWrapper):
    def __init__(self) -> None:
        EClient.__init__(self, self)
        self.next_valid_id = None

    def nextValidId(self, orderId: int) -> None:  # noqa: N802 - IB API callback
        self.next_valid_id = orderId
        logger.debug(f"IB nextValidId -> {orderId}")

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

        logger.error(f"IB error {errorCode}: {errorString}")
        if extra:
            logger.error(f"IB extra info: {extra}")


@log_result
def connect_ib(
    client_id: int | None = None,
    host: str = "127.0.0.1",
    port: int = 7497,
    timeout: int = 5,
    *,
    unique: bool = False,
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
    app = IBClient()

    try:
        logger.debug(f"Connecting to IB host={host} port={port} client_id={client_id}")
        app.connect(host, port, client_id)
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
