"""Shared file-system helpers for consistent storage access."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Iterable, List, Sequence

from tomic.helpers.json_utils import dump_json
from tomic.logutils import logger

PathLike = str | Path
DefaultFactory = Callable[[], Any]


def _ensure_parent(path: PathLike) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_json(path: PathLike, *, default_factory: DefaultFactory | None = None) -> Any:
    """Return parsed JSON data from ``path`` or ``default_factory()`` when missing."""

    p = Path(path)
    factory = default_factory or list
    if not p.exists():
        return factory()
    try:
        with p.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        logger.error(f"Corrupted JSON at {p}")
        return factory()


def save_json(data: Any, path: PathLike) -> None:
    """Persist ``data`` to ``path`` using an atomic write."""

    p = _ensure_parent(path)
    tmp = p.with_name(f"temp_{p.name}")
    dump_json(data, tmp)
    tmp.replace(p)


def update_json_file(
    file: PathLike,
    new_record: dict,
    key_fields: Sequence[str],
    *,
    sort_key: str | Callable[[dict], Any] | None = "date",
) -> List[dict]:
    """Insert ``new_record`` into ``file`` ensuring unique records per key."""

    data = load_json(file, default_factory=list)
    if not isinstance(data, list):
        data = []
    filtered: list[dict] = []
    for record in data:
        if not isinstance(record, dict):
            continue
        if all(record.get(k) == new_record.get(k) for k in key_fields):
            continue
        filtered.append(record)
    filtered.append(new_record)
    if sort_key:
        if isinstance(sort_key, str):
            filtered.sort(key=lambda r: r.get(sort_key, ""))
        else:
            filtered.sort(key=sort_key)
    save_json(filtered, file)
    return filtered


def merge_json_records(
    file: PathLike,
    records: Iterable[dict],
    *,
    key: str = "date",
) -> int:
    """Merge ``records`` into ``file`` keyed by ``key``."""

    existing = load_json(file, default_factory=list)
    if not isinstance(existing, list):
        existing = []
    seen = {rec.get(key) for rec in existing if isinstance(rec, dict)}
    new_records = [rec for rec in records if isinstance(rec, dict) and rec.get(key) not in seen]
    if not new_records:
        return 0
    existing.extend(new_records)
    existing.sort(key=lambda rec: rec.get(key, ""))
    save_json(existing, file)
    return len(new_records)
