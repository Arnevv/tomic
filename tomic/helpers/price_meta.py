from __future__ import annotations

"""Utilities for tracking price history fetch timestamps."""

from pathlib import Path
from typing import Any, Mapping

from tomic.config import get as cfg_get
from tomic.logutils import logger
from tomic.journal.utils import load_json, save_json


CloseMeta = dict[str, Any]


def _normalize_close_meta(value: Any) -> CloseMeta:
    """Return normalized metadata mapping for close records."""

    meta: CloseMeta = {
        "fetched_at": None,
        "source": None,
        "baseline_active": False,
        "baseline_as_of": None,
    }

    if isinstance(value, Mapping):
        fetched_at = value.get("fetched_at") or value.get("timestamp") or value.get("last_fetch")
        source = value.get("source") or value.get("provider")
        baseline = value.get("baseline")
        baseline_active: bool | None = None
        baseline_as_of = None

        if isinstance(baseline, Mapping):
            baseline_active = baseline.get("active")  # type: ignore[assignment]
            baseline_as_of = baseline.get("as_of")
            if baseline_active is None:
                baseline_active = baseline.get("baseline_active")
        else:
            baseline_active = value.get("baseline_active") or value.get("baseline")
            baseline_as_of = value.get("baseline_as_of")

        if fetched_at:
            meta["fetched_at"] = str(fetched_at)
        if source:
            meta["source"] = str(source)
        if baseline_active is not None:
            meta["baseline_active"] = bool(baseline_active)
        if baseline_as_of:
            meta["baseline_as_of"] = str(baseline_as_of)

    elif isinstance(value, str) and value:
        meta["fetched_at"] = value

    return meta


def ensure_all_symbols(meta: dict[str, Any]) -> dict[str, Any]:
    """Ensure all configured symbols exist in ``meta``.

    Missing symbols from :func:`cfg_get("DEFAULT_SYMBOLS")` are initialised
    with an empty timestamp so that new tickers are tracked automatically.
    """

    for sym in [s.upper() for s in cfg_get("DEFAULT_SYMBOLS", [])]:
        entry = meta.get(sym)
        if isinstance(entry, Mapping):
            meta[sym] = _normalize_close_meta(entry)
        elif isinstance(entry, str):
            meta[sym] = _normalize_close_meta(entry)
        else:
            meta[sym] = _normalize_close_meta({})
    return meta


def load_price_meta() -> dict[str, Any]:
    """Return mapping of symbols to metadata entries."""
    path = Path(cfg_get("PRICE_META_FILE", "price_meta.json"))
    data = load_json(path)
    meta_raw: dict[str, Any] = data if isinstance(data, dict) else {}
    normalized: dict[str, Any] = {}
    for key, value in meta_raw.items():
        if isinstance(value, Mapping) and key.isupper():
            normalized[key] = _normalize_close_meta(value)
        elif isinstance(value, str) and key.isupper():
            normalized[key] = _normalize_close_meta(value)
        else:
            normalized[key] = value
    return ensure_all_symbols(normalized)


def save_price_meta(meta: dict[str, Any]) -> None:
    """Persist ``meta`` to :data:`PRICE_META_FILE`."""
    path = Path(cfg_get("PRICE_META_FILE", "price_meta.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        save_json(meta, path)
    except OSError as exc:  # pragma: no cover - I/O errors
        logger.error(f"⚠️ Kan metadata niet schrijven: {exc}")
