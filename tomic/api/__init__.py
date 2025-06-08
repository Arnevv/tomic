"""API interaction modules.

This package provides thin wrappers around the official `ibapi` modules.  The
``ibapi`` package is normally installed via ``pip`` but many users download the
official Interactive Brokers API bundle instead.  In that case the Python
client lives in ``source/pythonclient`` and isn't automatically on the
``PYTHONPATH``.  The helper below adds support for this scenario so that imports
like ``from ibapi.contract import Contract`` keep working.
"""

from __future__ import annotations

import importlib
import os
import sys

# Fallback to local ``lib`` directory containing ``ibapi`` if available
lib_path = os.path.join(os.path.dirname(__file__), "..", "..", "lib")
sys.path.insert(0, os.path.abspath(lib_path))


def _ensure_ibapi() -> None:
    """Ensure the ``ibapi`` package can be imported.

    If the package isn't installed, an environment variable ``TWS_API_PATH`` or
    ``IB_API_PATH`` can be set to the folder containing the ``ibapi`` package
    (usually ``source/pythonclient`` from the official API download).
    """

    try:
        importlib.import_module("ibapi.contract")
        return
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on environment
        if exc.name in {"google", "google.protobuf"}:
            raise ModuleNotFoundError(
                "Missing dependency 'protobuf'. Install via 'pip install protobuf'"
            ) from exc
        pass

    api_path = os.getenv("TWS_API_PATH") or os.getenv("IB_API_PATH")
    if api_path:
        sys.path.append(api_path)
        try:
            importlib.import_module("ibapi.contract")
            return
        except ModuleNotFoundError as exc:  # pragma: no cover - misconfigured
            if exc.name in {"google", "google.protobuf"}:
                raise ModuleNotFoundError(
                    "Missing dependency 'protobuf'. Install via 'pip install protobuf'"
                ) from exc
            raise ModuleNotFoundError(
                "ibapi package not found in provided TWS_API_PATH / IB_API_PATH"
            ) from exc

    raise ModuleNotFoundError(
        "No module named 'ibapi'. Install via pip or set TWS_API_PATH/IB_API_PATH"
    )


_ensure_ibapi()
