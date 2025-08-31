from __future__ import annotations

from typing import Any, Callable, Dict, Mapping, Tuple
import warnings

MappingType = Mapping[str, Tuple[str, Callable[[Any], Any] | None]]


def normalize_config(rules: Dict[str, Any], mapping: MappingType) -> None:
    """Normalize legacy configuration fields.

    Parameters
    ----------
    rules:
        Configuration dictionary to normalize in place.
    mapping:
        Dictionary mapping legacy keys to tuples of (new_key, transform).
        The transform callable, if provided, is applied to the value before
        assigning it to the new key.
    """
    for old, (new, transform) in mapping.items():
        if old in rules and new not in rules:
            val = rules.pop(old)
            if transform:
                val = transform(val)
            warnings.warn(
                f"'{old}' is deprecated; use '{new}' instead",
                DeprecationWarning,
                stacklevel=3,
            )
            rules[new] = val


__all__ = ["normalize_config"]
