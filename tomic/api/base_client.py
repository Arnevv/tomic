"""Shared base classes for IB API clients."""

from __future__ import annotations

from .ib_connection import IBClient
from tomic.logutils import logger


class BaseIBApp(IBClient):
    """Base application using :class:`IBClient`."""

    #: Error codes that will be ignored by :meth:`error`.
    IGNORED_ERROR_CODES: set[int] = set()
    #: Error codes that should be logged as warnings.
    WARNING_ERROR_CODES: set[int] = set()


    def __init__(self) -> None:
        super().__init__()

    # The IB API wrapper expects an ``error`` callback with the full
    # signature ``(reqId, errorTime, errorCode, errorString, advancedOrderRejectJson)``.
    # ``IBClient`` defines a minimal placeholder method, so we override it here to
    # ensure compatibility and provide basic logging behaviour.
    def error(
        self,
        reqId: int,
        errorTime: int,
        errorCode: int,
        errorString: str,
        advancedOrderRejectJson: str = "",
    ) -> None:  # noqa: D401 - simple wrapper
        """Handle error messages from the IB API."""

        if errorCode in self.IGNORED_ERROR_CODES:
            logger.debug("IB error %s ignored: %s", errorCode, errorString)
            return

        if errorCode in self.WARNING_ERROR_CODES:
            logger.warning("IB warning %s: %s", errorCode, errorString)
        else:
            logger.error("IB error %s: %s", errorCode, errorString)


__all__ = ["BaseIBApp"]
