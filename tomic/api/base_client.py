"""Shared base classes for IB API clients."""

from __future__ import annotations

from .ib_connection import IBClient


class BaseIBApp(IBClient):
    """Base application using :class:`IBClient`."""

    def __init__(self) -> None:
        IBClient.__init__(self)


__all__ = ["BaseIBApp"]
