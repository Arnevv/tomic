"""API interaction modules.

This package provides thin wrappers around the official `ibapi` modules.
The `ibapi` package is normally installed via `pip`, but many users download the
official Interactive Brokers API bundle instead. In that case the Python client
lives in `source/pythonclient` or a `lib/` folder, and isn't automatically on the PYTHONPATH.
"""

from __future__ import annotations

import importlib
import os
import sys

def _ensure_ibapi() -> None:
    """Ensure the `ibapi` package can be imported.

    Tries the following in order:
    1. Native pip install
    2. Environment variable (TWS_API_PATH or IB_API_PATH)
    3. Local fallback path: ./lib/ibapi
    """

    # Check 1: native pip install
    try:
        importlib.import_module("ibapi.contract")
        return
    except ModuleNotFoundError as exc:
        if exc.name in {"google", "google.protobuf"}:
            raise ModuleNotFoundError(
                "Missing dependency 'protobuf'. Install via 'pip install protobuf'"
            ) from exc
        # continue to check alt paths

    # Check 2: environment variable path
    api_path = os.getenv("TWS_API_PATH") or os.getenv("IB_API_PATH")
    if api_path:
        sys.path.insert(0, api_path)
        try:
            importlib.import_module("ibapi.contract")
            return
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "ibapi package not found in TWS_API_PATH / IB_API_PATH → "
                f"tried: {api_path}"
            ) from exc

    # Check 3: fallback to ./lib/ibapi/
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    fallback_path = os.path.join(project_root, "lib")
    if os.path.exists(os.path.join(fallback_path, "ibapi")):
        sys.path.insert(0, fallback_path)
        try:
            importlib.import_module("ibapi.contract")
            return
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                f"ibapi not found in fallback path: {fallback_path}"
            ) from exc

    # All options exhausted
    raise ModuleNotFoundError(
        "No module named 'ibapi'. Install via pip or set TWS_API_PATH/IB_API_PATH "
        "or place 'ibapi' in a local ./lib/ folder."
    )

_ensure_ibapi()
