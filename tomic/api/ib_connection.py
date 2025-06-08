import threading
import time
import socket
from ibapi.client import EClient
from ibapi.wrapper import EWrapper

import sys
import os

PROTOBUF_PATH = os.path.join(os.path.dirname(__file__), "..", "ibapi", "protobuf")
sys.path.insert(0, os.path.abspath(PROTOBUF_PATH))

class IBClient(EClient, EWrapper):
    def __init__(self) -> None:
        EClient.__init__(self, self)
        self.next_valid_id = None

    def nextValidId(self, orderId: int) -> None:  # noqa: N802 - IB API callback
        self.next_valid_id = orderId

    # Match the signature expected by :class:`ibapi.wrapper.EWrapper` so
    # callbacks from the decoder don't fail if additional arguments are passed.
    def error(
        self,
        reqId: int,
        errorCode: int = None,
        errorString: str = None,
        errorTime: int = None,
        advancedOrderRejectJson: str = None,
    ) -> None:
        """Robuuste error handler voor verschillende API versies."""

        # Fallback als errorTime / advancedOrderRejectJson niet wordt meegegeven
        if errorCode is not None and errorString is not None:
            print(f"IB error {errorCode}: {errorString}")
        else:
            print(
                f"IB error: unexpected args reqId={reqId}, errorCode={errorCode}, errorString={errorString}"
            )

        if advancedOrderRejectJson:
            print(f"Advanced order reject: {advancedOrderRejectJson}")


def connect_ib(client_id=1, host="127.0.0.1", port=7497, timeout=5) -> IBClient:
    app = IBClient()

    try:
        app.connect(host, port, client_id)
    except socket.error as e:
        raise RuntimeError(f"❌ Kon niet verbinden met TWS op {host}:{port}: {e}")

    thread = threading.Thread(target=app.run)
    thread.start()

    start = time.time()
    while app.next_valid_id is None:
        if time.time() - start > timeout:
            raise TimeoutError("⏱ Timeout bij wachten op nextValidId")
        time.sleep(0.1)

    return app
