from __future__ import annotations

"""Utilities for tracking price history fetch timestamps."""

from pathlib import Path

from tomic.config import get as cfg_get
from tomic.logutils import logger
from tomic.journal.utils import load_json, save_json


def ensure_all_symbols(meta: dict[str, str]) -> dict[str, str]:
    """Ensure all configured symbols exist in ``meta``.

    Missing symbols from :func:`cfg_get("DEFAULT_SYMBOLS")` are initialised
    with an empty timestamp so that new tickers are tracked automatically.
    """

    for sym in [s.upper() for s in cfg_get("DEFAULT_SYMBOLS", [])]:
        meta.setdefault(sym, "")
    return meta


def load_price_meta() -> dict[str, str]:
    """Return mapping of symbols to ISO timestamp strings."""
    path = Path(cfg_get("PRICE_META_FILE", "price_meta.json"))
    data = load_json(path)
    meta = data if isinstance(data, dict) else {}
    return ensure_all_symbols(meta)


def save_price_meta(meta: dict[str, str]) -> None:
    """Persist ``meta`` to :data:`PRICE_META_FILE`."""
    path = Path(cfg_get("PRICE_META_FILE", "price_meta.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        save_json(meta, path)
    except OSError as exc:  # pragma: no cover - I/O errors
        logger.error(f"⚠️ Kan metadata niet schrijven: {exc}")
