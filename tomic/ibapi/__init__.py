
"""Initialization for the bundled IB API package.

This repository vendors a slightly modified copy of the official Interactive
Brokers API under ``tomic.ibapi``.  The generated protocol buffer modules inside
``tomic.ibapi.protobuf`` use absolute imports such as ``import Contract_pb2``.
Without adjusting ``sys.path`` those imports fail when ``tomic.ibapi`` is used
as a package, because the protobuf directory isn't on ``sys.path`` by default.

To make the protobuf modules importable regardless of the working directory we
add the ``protobuf`` directory to ``sys.path`` during package initialization.
"""

from __future__ import annotations

import os
import sys

_PROTOBUF_DIR = os.path.join(os.path.dirname(__file__), "protobuf")
if _PROTOBUF_DIR not in sys.path:
    sys.path.insert(0, _PROTOBUF_DIR)

__all__ = []
