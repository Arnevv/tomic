from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
from typing import Any, Union

from tomic.logutils import logger

PathLike = Union[str, Path]


def _default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


def dump_json(data: Any, path: PathLike, **kwargs) -> None:
    """Write data to a JSON file.

    Raises:
        OSError: If the file cannot be written.
        TypeError: If the data cannot be serialized.
    """
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=_default, **kwargs)
    except OSError as exc:
        logger.error(f"Failed to write JSON to {p}: {exc}")
        raise
    except TypeError as exc:
        logger.error(f"Failed to serialize data to JSON: {exc}")
        raise
