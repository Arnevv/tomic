"""Test that a basic IB API connection can be created.

This version uses lightweight stubs so the test can run without the actual
``ibapi`` or a running TWS instance. The goal is simply to exercise the
``connect`` and ``run`` flow.
"""

from __future__ import annotations

# mypy: disable-error-code=import-not-found

import builtins
from typing import Protocol


try:  # pragma: no cover - optional import for type checking
    from ibapi.client import EClient as RealClient
    from ibapi.wrapper import EWrapper as RealWrapper
except Exception:  # pragma: no cover - library not installed
    RealClient = None  # type: ignore[assignment]
    RealWrapper = None  # type: ignore[assignment]


class _ClientProto(Protocol):
    def connect(self, host: str, port: int, clientId: int) -> None:  # noqa: N802
        ...

    def run(self) -> None: ...

    def disconnect(self) -> None: ...


class DummyWrapper:
    """Minimal ``EWrapper`` replacement for offline tests."""

    def error(
        self,
        reqId: int,
        errorTime: int,
        errorCode: int,
        errorString: str,
        advancedOrderRejectJson: str = "",
    ) -> None:  # noqa: N802
        builtins.print(f"❌ Error {errorCode}: {errorString}")


class DummyClient:
    """Minimal ``EClient`` replacement for offline tests."""

    def __init__(self, wrapper: DummyWrapper) -> None:
        self.wrapper = wrapper
        self.connected = False

    def connect(self, host: str, port: int, clientId: int) -> None:  # noqa: N802
        self.connected = True

    def run(self) -> None:
        if hasattr(self.wrapper, "nextValidId"):
            self.wrapper.nextValidId(1)  # type: ignore[arg-type]

    def disconnect(self) -> None:
        self.connected = False


EClient = RealClient or DummyClient
EWrapper = RealWrapper or DummyWrapper


def test_tws_connection() -> None:
    class TestApp(EWrapper, EClient):  # type: ignore[misc, valid-type]
        def __init__(self) -> None:
            EClient.__init__(self, self)
            self.order_id: int | None = None

        def nextValidId(self, orderId: int) -> None:  # noqa: N802
            self.order_id = orderId
            self.disconnect()

    app: _ClientProto = TestApp()
    app.connect("127.0.0.1", 7497, clientId=1001)
    app.run()

    assert getattr(app, "order_id", None) == 1
