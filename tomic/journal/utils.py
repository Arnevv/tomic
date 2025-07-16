"""Utility helpers for reading and writing journal data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, List, Union

from tomic.config import get as cfg_get
from tomic import config
from tomic.helpers.json_utils import dump_json
from tomic.logutils import logger

_default = cfg_get("JOURNAL_FILE", str(config._BASE_DIR / "journal.json"))
JOURNAL_FILE = Path(_default).expanduser()
if not JOURNAL_FILE.is_absolute():
    JOURNAL_FILE = config._BASE_DIR / JOURNAL_FILE


PathLike = Union[str, Path]


def load_json(path: PathLike) -> Any:
    """Return parsed JSON from ``path`` or an empty list."""

    p = Path(path)
    if not p.exists():
        return []
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.error(f"Corrupted JSON at {p}")
        return []


def save_json(data: Any, path: PathLike) -> None:
    """Write ``data`` to ``path`` as JSON."""

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"temp_{p.name}")
    dump_json(data, tmp)
    tmp.replace(p)


def load_journal(path: PathLike = JOURNAL_FILE) -> List[Any]:
    """Return parsed journal data or an empty list if file is missing."""

    data = load_json(path)
    return list(data) if isinstance(data, list) else []


def save_journal(journal: Iterable[Any], path: PathLike = JOURNAL_FILE) -> None:
    """Write journal data back to ``path``."""

    save_json(list(journal), path)


def update_json_file(file: Path, new_record: dict, key_fields: list[str]) -> None:
    """Add or replace ``new_record`` in ``file`` using ``key_fields`` as key."""
    file.parent.mkdir(parents=True, exist_ok=True)
    data = load_json(file)
    if not isinstance(data, list):
        data = []
    data = [
        r
        for r in data
        if not all(r.get(k) == new_record.get(k) for k in key_fields)
    ]
    data.append(new_record)
    if "date" in new_record:
        data.sort(key=lambda r: r.get("date", ""))
    save_json(data, file)
