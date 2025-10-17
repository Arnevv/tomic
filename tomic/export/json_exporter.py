"""JSON exporter for proposal data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .utils import RunMetadata


def export_proposals_json(
    records: Mapping[str, Any],
    *,
    path: str | Path,
    run_meta: RunMetadata,
) -> Path:
    """Serialise ``records`` combined with ``run_meta`` to ``path``."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": run_meta.as_dict(),
        "data": records,
    }
    with target.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, default=_json_default)
    return target


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except TypeError:
            pass
    return str(value)
