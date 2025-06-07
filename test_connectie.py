def test_tws_connection():
    from ibapi.client import EClient
    from ibapi.wrapper import EWrapper

    class TestApp(EWrapper, EClient):
        def __init__(self):
            EClient.__init__(self, self)

        def nextValidId(self, orderId):
            print("✅ Connected with Order ID:", orderId)
            self.disconnect()

        def error(self, reqId, errorCode, errorString):
            print(f"❌ Error: {errorCode} – {errorString}")

    app = TestApp()
    app.connect("127.0.0.1", 7497, clientId=1)
    app.run()
