from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
from typing import Any, Union

PathLike = Union[str, Path]


def _default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


def dump_json(data: Any, path: PathLike, **kwargs) -> None:
    p = Path(path)
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=_default, **kwargs)
