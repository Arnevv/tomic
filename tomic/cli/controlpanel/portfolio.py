"""Bridge module exposing UI handlers and core portfolio services."""

from __future__ import annotations

from types import ModuleType
import sys

from tomic.core.portfolio import services as _services
from . import portfolio_ui as _ui

__all__ = list(getattr(_ui, "__all__", [])) + list(_services.__all__)


class _PortfolioProxy(ModuleType):
    """Module proxy that delegates attribute access to UI and service layers."""

    def __getattr__(self, name: str):  # type: ignore[override]
        if hasattr(_ui, name):
            return getattr(_ui, name)
        if hasattr(_services, name):
            return getattr(_services, name)
        raise AttributeError(name)

    def __setattr__(self, name: str, value):  # type: ignore[override]
        if hasattr(_ui, name):
            setattr(_ui, name, value)
        else:
            super().__setattr__(name, value)


module = sys.modules[__name__]
module.__class__ = _PortfolioProxy  # type: ignore[misc]

# Ensure SHOW_REASONS mirrors the UI state for backward compatibility.
if hasattr(_ui, "SHOW_REASONS"):
    module.SHOW_REASONS = getattr(_ui, "SHOW_REASONS")
