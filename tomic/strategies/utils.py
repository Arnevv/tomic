"""Utility helpers for strategy modules."""

from __future__ import annotations

from typing import Sequence, Any

from ..logutils import logger


def validate_width_list(widths: Sequence[Any] | None, key: str) -> Sequence[Any]:
    """Return ``widths`` if valid or raise ``ValueError``.

    Parameters
    ----------
    widths:
        The sequence of width values retrieved from configuration.
    key:
        The configuration key the widths originate from. Used for a clear
        error message when validation fails.

    Raises
    ------
    ValueError
        If ``widths`` is ``None`` or empty.
    """

    if not widths:
        msg = f"'{key}' ontbreekt of is leeg in configuratie"
        logger.error(msg)
        raise ValueError(msg)
    return widths


__all__ = ["validate_width_list"]

