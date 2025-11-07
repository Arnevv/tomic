"""Shims for removed TWS option-chain functionality."""

from __future__ import annotations

from tomic.logutils import logger


def removed_tws_chain_entry(*_: object, **__: object) -> None:
    """Raise an informative error for removed TWS chain entrypoints."""

    message = (
        "TWS option-chain export is verwijderd. Gebruik Polygon-paden. "
        "Start via Polygon: Control Panel → Marktinformatie."
    )
    logger.error(message)
    raise RuntimeError(message)
