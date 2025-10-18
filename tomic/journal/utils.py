"""Utility helpers for reading and writing journal data."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, List

from tomic.config import get as cfg_get
from tomic import config
from tomic.infrastructure.storage import (
    PathLike,
    load_json as storage_load_json,
    save_json as storage_save_json,
    update_json_file as storage_update_json_file,
)

_default = cfg_get("JOURNAL_FILE", str(config._BASE_DIR / "journal.json"))
JOURNAL_FILE = Path(_default).expanduser()
if not JOURNAL_FILE.is_absolute():
    JOURNAL_FILE = config._BASE_DIR / JOURNAL_FILE


def load_json(path: PathLike) -> Any:
    """Return parsed JSON from ``path`` or an empty list."""

    data = storage_load_json(path, default_factory=list)
    if not isinstance(data, list):
        return data
    return data


def save_json(data: Any, path: PathLike) -> None:
    """Write ``data`` to ``path`` as JSON."""

    storage_save_json(data, path)


def load_journal(path: PathLike = JOURNAL_FILE) -> List[Any]:
    """Return parsed journal data or an empty list if file is missing."""

    data = load_json(path)
    return list(data) if isinstance(data, list) else []


def save_journal(journal: Iterable[Any], path: PathLike = JOURNAL_FILE) -> None:
    """Write journal data back to ``path``."""

    save_json(list(journal), path)


def update_json_file(file: Path, new_record: dict, key_fields: list[str]) -> None:
    """Add or replace ``new_record`` in ``file`` using ``key_fields`` as key."""
    storage_update_json_file(file, new_record, key_fields)
