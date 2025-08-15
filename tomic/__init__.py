"""TOMIC core package.

The project exposes a number of helper modules as well as a validated
configuration object.  Importing :mod:`tomic` will make the rules
configuration available as :data:`RULES`.
"""

from .criteria import RULES

__all__ = ["RULES"]
