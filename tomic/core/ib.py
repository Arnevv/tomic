"""Base IB application with connection and error handling helpers."""

from __future__ import annotations

import threading
from ibapi.client import EClient
from ibapi.wrapper import EWrapper

from tomic.config import get as cfg_get
from tomic.logging import logger


class BaseApp(EWrapper, EClient):
    """Base class for IB API apps providing connect/start helpers."""

    IGNORED_ERROR_CODES: set[int] = {2104, 2106, 2158, 2176}
    WARNING_ERROR_CODES: set[int] = set()

    def __init__(self) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self._thread: threading.Thread | None = None

    def start(
        self,
        host: str | None = None,
        port: int | None = None,
        client_id: int = 0,
    ) -> threading.Thread:
        """Connect to IB and start the network thread."""
        host = host or cfg_get("IB_HOST", "127.0.0.1")
        port = int(port or cfg_get("IB_PORT", 7497))
        super().connect(host, port, clientId=client_id)
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()
        return self._thread

    def disconnect(self) -> None:  # type: ignore[override]
        super().disconnect()
        if (
            self._thread
            and self._thread.is_alive()
            and threading.current_thread() is not self._thread
        ):
            # Ensure the network thread fully stops before continuing
            self._thread.join()
        self._thread = None

    def error(self, reqId: int, errorCode: int, errorString: str) -> None:  # noqa: N802
        """Default error handler logging using :mod:`loguru`."""
        if errorCode in self.IGNORED_ERROR_CODES:
            logger.debug("IB: {} {}", errorCode, errorString)
        elif errorCode in self.WARNING_ERROR_CODES:
            logger.warning("\u26a0\ufe0f Error {}: {}", errorCode, errorString)
        else:
            logger.error("\u26a0\ufe0f Error {}: {}", errorCode, errorString)


__all__ = ["BaseApp"]
