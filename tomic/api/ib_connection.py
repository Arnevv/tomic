import threading
import time
import socket
from ibapi.client import EClient
from ibapi.wrapper import EWrapper

class IBClient(EClient, EWrapper):
    def __init__(self):
        EClient.__init__(self, self)
        self.next_valid_id = None

    def nextValidId(self, orderId: int):
        self.next_valid_id = orderId

    def error(self, reqId, errorCode, errorString):
        print(f"IB error {errorCode}: {errorString}")


def connect_ib(client_id=1, host="127.0.0.1", port=7497, timeout=5) -> IBClient:
    app = IBClient()

    try:
        app.connect(host, port, client_id)
    except socket.error as e:
        raise RuntimeError(f"❌ Kon niet verbinden met TWS op {host}:{port}: {e}")

    thread = threading.Thread(target=app.run, daemon=True)
    thread.start()

    start = time.time()
    while app.next_valid_id is None:
        if time.time() - start > timeout:
            raise TimeoutError("⏱ Timeout bij wachten op nextValidId")
        time.sleep(0.1)

    return app
