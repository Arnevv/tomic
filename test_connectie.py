import pytest
from typing import TYPE_CHECKING

# mypy: disable-error-code=import-not-found

if TYPE_CHECKING:  # pragma: no cover - import for type checking only
    from ibapi.client import EClient  # noqa: F401
    from ibapi.wrapper import EWrapper  # noqa: F401


def test_tws_connection():
    try:
        import google.protobuf  # noqa: F401
    except Exception:
        pytest.skip("google protobuf not installed")

    try:
        from ibapi.client import EClient
        from ibapi.wrapper import EWrapper
    except Exception:
        try:
            from lib.ibapi import EClient
            from lib.ibapi import EWrapper
        except Exception:
            pytest.skip("ibapi not available")
    if not hasattr(EClient, "connect"):
        pytest.skip("ibapi stub")

    class TestApp(EWrapper, EClient):
        def __init__(self):
            EClient.__init__(self, self)

        def nextValidId(self, orderId):
            print("✅ Connected with Order ID:", orderId)
            self.disconnect()

        def error(self, reqId, errorCode, errorString):
            print(f"❌ Error: {errorCode} – {errorString}")

    app = TestApp()
    app.connect("127.0.0.1", 7497, clientId=1001)
    app.run()
