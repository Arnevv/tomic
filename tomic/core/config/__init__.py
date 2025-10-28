"""Lightweight hierarchical runtime configuration."""

from __future__ import annotations

import json
import os
import threading
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from tomic.core.config_models import ConfigBase
from tomic.config import _load_yaml


class EarningsImportConfig(BaseModel):
    today_override: date | None = None
    symbol_col: str = "Symbol"
    next_col_candidates: list[str] = Field(
        default_factory=lambda: ["Next Earnings", "Next Earnings "]
    )


class ImportState(BaseModel):
    last_earnings_csv_path: str | None = None


class DataConfig(BaseModel):
    earnings_json_path: str | None = None


class RuntimeConfig(ConfigBase):
    version: int = 1
    earnings_import: EarningsImportConfig = EarningsImportConfig()
    import_state: ImportState = Field(default_factory=ImportState, alias="import")
    data: DataConfig = Field(default_factory=DataConfig)

    model_config = {
        "populate_by_name": True,
        "extra": "ignore",
    }


DEFAULT_PATH = (
    Path(os.environ.get("TOMIC_RUNTIME_CONFIG", ""))
    if os.environ.get("TOMIC_RUNTIME_CONFIG")
    else Path(__file__).resolve().parents[2] / "config" / "runtime.yaml"
)

_LOCK = threading.Lock()
_CONFIG_PATH = DEFAULT_PATH


def _load_config(path: Path) -> RuntimeConfig:
    if not path.exists():
        return RuntimeConfig()
    raw = _load_yaml(path)
    if not isinstance(raw, dict):
        return RuntimeConfig()
    return RuntimeConfig.model_validate(raw)


_RUNTIME_CONFIG = _load_config(_CONFIG_PATH)


def _dump_yaml(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import yaml  # type: ignore

        with path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(data, handle, sort_keys=False)
    except Exception:
        with path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, default=str)


def load(path: Path | None = None) -> RuntimeConfig:
    """Return the current runtime configuration."""

    global _RUNTIME_CONFIG, _CONFIG_PATH
    with _LOCK:
        target = path or _CONFIG_PATH
        _CONFIG_PATH = target
        _RUNTIME_CONFIG = _load_config(target)
        return _RUNTIME_CONFIG


def get(path: str, default: Any | None = None) -> Any:
    """Return value stored at ``path`` using dot-notation."""

    with _LOCK:
        current = _RUNTIME_CONFIG.model_dump(by_alias=True)
    parts = path.split(".")
    node: Any = current
    for part in parts:
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return default
    return node


def set_value(path: str, value: Any) -> None:
    """Set ``path`` to ``value`` and persist the configuration."""

    with _LOCK:
        data = _RUNTIME_CONFIG.model_dump(by_alias=True)
        _assign(data, path.split("."), value)
        config = RuntimeConfig.model_validate(data)
        _dump_yaml(config.model_dump(by_alias=True), _CONFIG_PATH)
        _RUNTIME_CONFIG.__dict__.update(config.__dict__)


def _assign(target: dict[str, Any], parts: list[str], value: Any) -> None:
    if not parts:
        return
    head, *tail = parts
    if not tail:
        target[head] = value
        return
    child = target.setdefault(head, {})
    if not isinstance(child, dict):
        child = {}
        target[head] = child
    _assign(child, tail, value)


__all__ = [
    "RuntimeConfig",
    "EarningsImportConfig",
    "ImportState",
    "DataConfig",
    "load",
    "get",
    "set_value",
]


# Ensure configuration is loaded when the module is imported.
load(_CONFIG_PATH)

