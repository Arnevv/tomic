"""Helpers for export metadata and path handling."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import json
import re


_SANITIZE_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class RunMetadata:
    """Metadata describing an export run."""

    timestamp: datetime
    run_id: str
    config_hash: str | None = None
    symbol: str | None = None
    strategy: str | None = None
    schema_version: str | None = None
    extra: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return a serialisable representation of the metadata."""

        payload: dict[str, Any] = {
            "timestamp": self.timestamp.isoformat(timespec="seconds"),
            "run_id": self.run_id,
        }
        if self.config_hash:
            payload["config_hash"] = self.config_hash
        if self.symbol:
            payload["symbol"] = self.symbol
        if self.strategy:
            payload["strategy"] = self.strategy
        if self.schema_version:
            payload["schema_version"] = self.schema_version
        if self.extra:
            payload["extra"] = _ensure_jsonable(self.extra)
        return payload

    def with_extra(
        self, extra: Mapping[str, Any] | None = None, **updates: Any
    ) -> "RunMetadata":
        """Return a copy with ``extra`` merged with ``updates``."""

        if not extra and not updates:
            return self
        merged: dict[str, Any] = {}
        if self.extra:
            merged.update(self.extra)
        if extra:
            merged.update(extra)
        if updates:
            merged.update(updates)
        return replace(self, extra=merged)


def build_export_path(
    kind: str,
    run_meta: RunMetadata,
    *,
    extension: str,
    directory: str | Path,
    tags: Sequence[str] | None = None,
) -> Path:
    """Return a filesystem path for ``kind`` using ``run_meta`` and ``tags``."""

    base_dir = Path(directory)
    date_dir = base_dir / run_meta.timestamp.strftime("%Y%m%d")
    date_dir.mkdir(parents=True, exist_ok=True)

    parts: list[str] = [run_meta.timestamp.strftime("%Y%m%dT%H%M%S")]
    if run_meta.symbol:
        parts.append(run_meta.symbol)
    parts.append(kind)
    if run_meta.strategy and run_meta.strategy not in parts:
        parts.append(run_meta.strategy)
    if tags:
        parts.extend(tag for tag in tags if tag)
    parts.append(run_meta.run_id)
    if run_meta.config_hash:
        parts.append(run_meta.config_hash)
    if run_meta.schema_version:
        parts.append(f"v{run_meta.schema_version}")

    sanitized = [_sanitize_token(part) for part in parts if part]
    filename = "_".join(token for token in sanitized if token)
    ext = extension.lstrip(".")
    return date_dir / f"{filename}.{ext}"


def _sanitize_token(value: str) -> str:
    normalized = value.strip().replace(" ", "-")
    normalized = _SANITIZE_PATTERN.sub("-", normalized)
    return normalized.strip("-")


def _ensure_jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        if isinstance(value, Mapping):
            return {k: _ensure_jsonable(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [_ensure_jsonable(v) for v in value]
        if isinstance(value, datetime):
            return value.isoformat(timespec="seconds")
        return str(value)
