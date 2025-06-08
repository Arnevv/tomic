import sys
import types

# Create minimal stubs so base_client can be imported without the real IB API
client_stub = types.ModuleType("ibapi.client")
client_stub.EClient = type("EClient", (), {"__init__": lambda self, wrapper=None: None})
wrapper_stub = types.ModuleType("ibapi.wrapper")
wrapper_stub.EWrapper = type("EWrapper", (), {})
sys.modules.setdefault("ibapi.client", client_stub)
sys.modules.setdefault("ibapi.wrapper", wrapper_stub)

from tomic.api.base_client import BaseIBApp


def test_baseibapp_error_signature():
    class DummyApp(BaseIBApp):
        IGNORED_ERROR_CODES = BaseIBApp.IGNORED_ERROR_CODES | {999}

    app = DummyApp()
    app.error(1, 0, 999, "ignored", "")
    app.error(1, 0, 100, "msg", "")
    assert hasattr(BaseIBApp, "IGNORED_ERROR_CODES")
