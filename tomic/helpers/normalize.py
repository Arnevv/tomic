from __future__ import annotations

from typing import Any, Callable, Mapping, MutableMapping, Tuple
import warnings

MappingType = Mapping[str, Tuple[str, Callable[[Any], Any] | None]]


def normalize_config(
    rules: Mapping[str, Any],
    mapping: MappingType | None = None,
    *,
    strategy: str | None = None,
) -> dict[str, Any]:
    """Return ``rules`` with deprecated keys mapped to canonical names.

    Parameters
    ----------
    rules:
        Configuration dictionary to normalize.
    mapping:
        Optional mapping of legacy keys to tuples of (new_key, transform). When
        provided, the transform callable, if any, is applied before assigning
        the value to ``new_key``. If omitted, built-in strike rule field
        mappings are applied.
    strategy:
        Optional strategy name used for strategy specific field mappings when
        applying the built-in strike rule normalizations.
    """

    normalized: MutableMapping[str, Any] = dict(rules)

    if mapping is not None:
        for old, (new, transform) in mapping.items():
            if old in normalized and new not in normalized:
                val = normalized.pop(old)
                if transform:
                    val = transform(val)
                warnings.warn(
                    f"'{old}' is deprecated; use '{new}' instead",
                    DeprecationWarning,
                    stacklevel=2,
                )
                normalized[new] = val
            else:
                normalized.pop(old, None)
        return dict(normalized)

    field_mapping: dict[str, str] = {
        "long_leg_distance": "long_leg_distance_points",
        "long_leg_target_delta": "long_leg_distance_points",
        "long_put_distance_points": "long_leg_distance_points",
        "long_call_distance_points": "long_leg_distance_points",
        "strike_distance": "base_strikes_relative_to_spot",
        "expiry_gap_min": "expiry_gap_min_days",
        "wing_width": "wing_width_points",
        "wing_width_points": "wing_width_sigma",
        "short_call_multiplier": "short_call_delta_range",
        "short_put_multiplier": "short_put_delta_range",
    }
    per_strategy: dict[str, dict[str, str]] = {
        "backspread_put": {"short_delta_range": "short_put_delta_range"},
        "naked_put": {"short_delta_range": "short_put_delta_range"},
        "short_put_spread": {"short_delta_range": "short_put_delta_range"},
        "short_call_spread": {"short_delta_range": "short_call_delta_range"},
        "ratio_spread": {"short_delta_range": "short_leg_delta_range"},
    }
    if strategy and strategy in per_strategy:
        field_mapping.update(per_strategy[strategy])

    for old, new in field_mapping.items():
        if old in normalized and new not in normalized:
            val = normalized.pop(old)
            warnings.warn(
                f"'{old}' is deprecated; use '{new}' instead",
                DeprecationWarning,
                stacklevel=2,
            )
            normalized[new] = val
        else:
            normalized.pop(old, None)

    if "wing_width_sigma" in normalized and "wing_sigma_multiple" not in normalized:
        normalized["wing_sigma_multiple"] = normalized.pop("wing_width_sigma")

    b = normalized.get("base_strikes_relative_to_spot")
    if b is not None and not isinstance(b, (list, tuple)):
        normalized["base_strikes_relative_to_spot"] = [b]

    w = normalized.get("wing_sigma_multiple")
    if isinstance(w, (list, tuple)):
        normalized["wing_sigma_multiple"] = w[0] if w else w

    return dict(normalized)


__all__ = ["normalize_config"]
