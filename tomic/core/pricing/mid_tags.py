"""Shared helpers for mid-source normalization and metadata tags."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator, Mapping, Sequence


# Canonical ordering for mid source counters in summaries and tags.
MID_SOURCE_ORDER: tuple[str, ...] = (
    "true",
    "parity_true",
    "parity_close",
    "model",
    "close",
)

# Preview-qualifying sources used to flag advisory statuses.
PREVIEW_SOURCES: tuple[str, ...] = ("parity_close", "model", "close")

# Sources considered trusted (not counted as fallbacks).
TRUSTED_SOURCES: frozenset[str] = frozenset({"true", "parity_true"})


def _iter_candidates(value: object) -> Iterator[object]:
    """Yield flattened candidates for mid source normalization."""

    if value is None:
        return
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, Mapping):
        for key in ("mid_source", "mid_fallback"):
            if key in value:
                yield value[key]
        return
    if hasattr(value, "mid_source") or hasattr(value, "mid_fallback"):
        mid_source = getattr(value, "mid_source", None)
        mid_fallback = getattr(value, "mid_fallback", None)
        if mid_source is not None:
            yield mid_source
        if mid_fallback is not None:
            yield mid_fallback
        return
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
        for item in value:
            yield from _iter_candidates(item)
        return
    yield value


def _normalize_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if not text:
        return None
    if text == "parity":
        return "parity_true"
    return text


def normalize_mid_source(
    raw_source: object,
    fallback_chain: Sequence[object] | Iterable[object] | None = None,
) -> str | None:
    """Return normalized mid source using ``fallback_chain`` when needed."""

    candidates: list[object] = [raw_source]
    if fallback_chain is not None:
        candidates.append(fallback_chain)

    for candidate in candidates:
        for item in _iter_candidates(candidate):
            normalized = _normalize_text(item)
            if normalized:
                return normalized
    return None


@dataclass(frozen=True, slots=True)
class MidTagSnapshot:
    """Immutable representation for mid source tags and counters."""

    tags: tuple[str, ...]
    counters: Mapping[str, int]

    def as_metadata(self) -> dict[str, object]:
        """Return a JSON-serializable representation of the snapshot."""

        return {
            "tags": list(self.tags),
            "counters": {key: int(value) for key, value in self.counters.items()},
        }

    def counter_items(self) -> Iterator[tuple[str, int]]:
        """Iterate over counter entries preserving canonical ordering."""

        seen = set()
        for source in MID_SOURCE_ORDER:
            if source in self.counters:
                seen.add(source)
                yield source, int(self.counters[source])
        for source, count in self.counters.items():
            if source not in seen:
                yield source, int(count)


__all__ = [
    "MID_SOURCE_ORDER",
    "PREVIEW_SOURCES",
    "TRUSTED_SOURCES",
    "MidTagSnapshot",
    "normalize_mid_source",
]

