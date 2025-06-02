"""Utility helpers for reading and writing journal data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, List, Union

from tomic.config import get as cfg_get

JOURNAL_FILE = Path(cfg_get("JOURNAL_FILE", "journal.json"))


PathLike = Union[str, Path]


def load_json(path: PathLike) -> Any:
    """Return parsed JSON from ``path`` or an empty list."""

    p = Path(path)
    if not p.exists():
        return []
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data: Any, path: PathLike) -> None:
    """Write ``data`` to ``path`` as JSON."""

    p = Path(path)
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_journal(path: PathLike = JOURNAL_FILE) -> List[Any]:
    """Return parsed journal data or an empty list if file is missing."""

    data = load_json(path)
    return list(data) if isinstance(data, list) else []


def save_journal(journal: Iterable[Any], path: PathLike = JOURNAL_FILE) -> None:
    """Write journal data back to ``path``."""

    save_json(list(journal), path)
