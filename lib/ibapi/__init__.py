"""
Copyright (C) 2023 Interactive Brokers LLC. All rights reserved. This code is subject to the terms
 and conditions of the IB API Non-Commercial License or the IB API Commercial License, as applicable.
"""

"""Package implementing the Python API for the TWS/IB Gateway.

This repository vendors the official ``ibapi`` package under ``lib.ibapi`` so
that it can be used without installing it system wide. Previous versions
re-exported several commonly used classes at package level (e.g. ``Contract`` or
``EClient``). The upstream package does not do this which caused imports such as
``from lib.ibapi import EClient`` to fail. To maintain backwards compatibility,
the most frequently used classes are re-exported here.
"""

# ruff: noqa: E402

import sys as _sys

VERSION = {"major": 10, "minor": 37, "micro": 2}


def get_version_string():
    version = "{major}.{minor}.{micro}".format(**VERSION)
    return version


__version__ = get_version_string()

# ---------------------------------------------------------------------------
# Make this package available as ``ibapi`` to mimic the standard installation
# layout. The individual modules (e.g. ``ibapi.client``) expect to be imported
# from a top-level ``ibapi`` package. By registering an alias in ``sys.modules``
# we allow imports of both ``ibapi`` and ``lib.ibapi`` to refer to this vendored
# copy without installing it site-wide.
_sys.modules.setdefault("ibapi", _sys.modules[__name__])

# Re-export key classes for convenience -------------------------------------
from .client import EClient, OrderId, TickerId
from .wrapper import EWrapper
from .contract import Contract, ContractDetails
from .ticktype import TickTypeEnum
from .order import Order
from .account_summary_tags import AccountSummaryTags

__all__ = [
    "EClient",
    "EWrapper",
    "Contract",
    "ContractDetails",
    "Order",
    "OrderId",
    "TickerId",
    "TickTypeEnum",
    "AccountSummaryTags",
    "get_version_string",
    "__version__",
]
