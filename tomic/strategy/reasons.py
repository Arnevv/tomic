"""Canonical reason types used across the strategy pipeline.

This module centralises the configuration used by the mid resolver, scoring
logic and CLI to reason about rejection causes.  Reasons are represented as
instances of :class:`ReasonDetail`, which combines a high level
``ReasonCategory`` with a concrete ``code`` and human readable ``message``.

The intent is to keep the mapping logic data driven rather than depending on
free form text.  New reason types or mid sources can therefore be surfaced by
adding a single definition here instead of sprinkling keyword checks through
the codebase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final, Iterable, Literal, Mapping, MutableMapping, Sequence


class ReasonCategory(str, Enum):
    """Canonical categories for rejection reasons."""

    MISSING_DATA = "MISSING_DATA"
    WIDE_SPREAD = "WIDE_SPREAD"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    RR_BELOW_MIN = "RR_BELOW_MIN"
    EV_BELOW_MIN = "EV_BELOW_MIN"
    PREVIEW_QUALITY = "PREVIEW_QUALITY"
    LOW_LIQUIDITY = "LOW_LIQUIDITY"
    OTHER = "OTHER"


ReasonCategoryLiteral = Literal[
    "MISSING_DATA",
    "WIDE_SPREAD",
    "POLICY_VIOLATION",
    "RR_BELOW_MIN",
    "EV_BELOW_MIN",
    "PREVIEW_QUALITY",
    "LOW_LIQUIDITY",
    "OTHER",
]


_CATEGORY_LABELS: Final[Mapping[ReasonCategory, str]] = {
    ReasonCategory.MISSING_DATA: "Ontbrekende data",
    ReasonCategory.WIDE_SPREAD: "Spread te wijd",
    ReasonCategory.POLICY_VIOLATION: "Policy/intern",
    ReasonCategory.RR_BELOW_MIN: "Risk/Reward",
    ReasonCategory.EV_BELOW_MIN: "EV onvoldoende",
    ReasonCategory.PREVIEW_QUALITY: "Previewkwaliteit",
    ReasonCategory.LOW_LIQUIDITY: "Lage liquiditeit",
    ReasonCategory.OTHER: "Overig",
}


_CATEGORY_PRIORITY: Final[Mapping[ReasonCategory, int]] = {
    ReasonCategory.MISSING_DATA: 0,
    ReasonCategory.WIDE_SPREAD: 1,
    ReasonCategory.POLICY_VIOLATION: 2,
    ReasonCategory.RR_BELOW_MIN: 3,
    ReasonCategory.EV_BELOW_MIN: 4,
    ReasonCategory.PREVIEW_QUALITY: 5,
    ReasonCategory.LOW_LIQUIDITY: 0,
    ReasonCategory.OTHER: 6,
}


_TRUE_MID_SOURCES: Final[set[str]] = {"true", "parity_true"}
_KNOWN_PREVIEW_SOURCES: Final[set[str]] = {"parity_close", "model", "close"}


@dataclass(frozen=True)
class ReasonDetail:
    """Structured representation of a rejection reason."""

    category: ReasonCategory
    code: str
    message: str
    data: Mapping[str, Any] = field(default_factory=dict)

    def with_message(self, message: str) -> "ReasonDetail":
        if message == self.message:
            return self
        return ReasonDetail(self.category, self.code, message, self.data)


ReasonLike = ReasonDetail | Mapping[str, Any] | ReasonCategory | str | None


def category_label(category: ReasonCategory) -> str:
    """Return the human readable label for ``category``."""

    return _CATEGORY_LABELS.get(category, category.value.title().replace("_", " "))


def category_priority(category: ReasonCategory) -> int:
    """Return the priority index for ``category``."""

    return _CATEGORY_PRIORITY.get(category, _CATEGORY_PRIORITY[ReasonCategory.OTHER])


def make_reason(
    category: ReasonCategory,
    code: str,
    message: str,
    *,
    data: Mapping[str, Any] | None = None,
) -> ReasonDetail:
    """Construct a :class:`ReasonDetail` with optional metadata."""

    payload = dict(data or {})
    return ReasonDetail(category=category, code=code, message=message, data=payload)


def reason_from_mid_source(mid_source: str | None) -> ReasonDetail | None:
    """Return a reason representing the quality of ``mid_source``.

    ``None`` is returned for high quality sources (``true``/``parity_true``).  All
    other non-empty sources map to :class:`ReasonCategory.PREVIEW_QUALITY` while
    an empty value is treated as missing data.  Unknown sources default to
    preview quality so that newly introduced fallbacks do not appear as missing
    data.
    """

    source = (mid_source or "").strip().lower()
    if not source:
        return make_reason(
            ReasonCategory.MISSING_DATA,
            "MID_MISSING",
            "mid ontbreekt",
            data={"mid_source": source or None},
        )
    if source in _TRUE_MID_SOURCES:
        return None
    label = f"previewkwaliteit ({source})"
    return make_reason(
        ReasonCategory.PREVIEW_QUALITY,
        f"PREVIEW_{source}" if source in _KNOWN_PREVIEW_SOURCES else "PREVIEW_FALLBACK",
        label,
        data={"mid_source": source},
    )


def _as_detail_from_mapping(mapping: Mapping[str, Any]) -> ReasonDetail:
    category_value = mapping.get("category")
    if isinstance(category_value, ReasonCategory):
        category = category_value
    elif isinstance(category_value, str):
        try:
            category = ReasonCategory(category_value)
        except ValueError as exc:  # pragma: no cover - defensive
            raise ValueError(f"Unknown reason category: {category_value!r}") from exc
    else:
        raise ValueError("reason mapping must include a 'category'")
    code = str(mapping.get("code") or category.value)
    message = str(mapping.get("message") or category_label(category))
    data = mapping.get("data")
    payload: Mapping[str, Any]
    if isinstance(data, Mapping):
        payload = dict(data)
    else:
        payload = {}
    return ReasonDetail(category=category, code=code, message=message, data=payload)


_LEGACY_PREFIX_MAP: MutableMapping[str, ReasonDetail] = {
    "geen expiries beschikbaar": make_reason(
        ReasonCategory.MISSING_DATA,
        "EXPIRY_NOT_AVAILABLE",
        "geen expiries beschikbaar",
    ),
    "geen strikes beschikbaar": make_reason(
        ReasonCategory.MISSING_DATA,
        "MISSING_STRIKES",
        "geen strikes beschikbaar",
    ),
    "opties niet gevonden": make_reason(
        ReasonCategory.MISSING_DATA,
        "OPTIONS_NOT_FOUND",
        "opties niet gevonden",
    ),
    "breedte niet berekend": make_reason(
        ReasonCategory.MISSING_DATA,
        "WIDTH_NOT_COMPUTED",
        "breedte niet berekend",
    ),
    "geen expiraties beschikbaar": make_reason(
        ReasonCategory.MISSING_DATA,
        "EXPIRY_NOT_AVAILABLE",
        "geen expiraties beschikbaar",
    ),
}


def _legacy_reason(original: str, lookup: str) -> ReasonDetail | None:
    detail = _LEGACY_REASON_MAP.get(lookup)
    if detail is not None:
        if original == detail.message:
            return detail
        payload = dict(detail.data)
        if original:
            payload.setdefault("original_message", original)
        return make_reason(detail.category, detail.code, detail.message, data=payload)
    for prefix, template in _LEGACY_PREFIX_MAP.items():
        if lookup.startswith(prefix):
            payload = dict(template.data)
            if original:
                payload.setdefault("original_message", original)
            return make_reason(template.category, template.code, template.message, data=payload)
    return None


def normalize_reason(raw_reason: ReasonLike) -> ReasonDetail:
    """Convert ``raw_reason`` into a :class:`ReasonDetail` instance."""

    if isinstance(raw_reason, ReasonDetail):
        return raw_reason
    if raw_reason is None:
        return make_reason(ReasonCategory.OTHER, "UNSPECIFIED", "geen reden opgegeven")
    if isinstance(raw_reason, ReasonCategory):
        return make_reason(raw_reason, raw_reason.value, category_label(raw_reason))
    if isinstance(raw_reason, Mapping):
        return _as_detail_from_mapping(raw_reason)
    if isinstance(raw_reason, str):
        stripped = raw_reason.strip()
        if not stripped:
            return make_reason(ReasonCategory.OTHER, "EMPTY", "geen reden opgegeven")
        lookup = stripped.lower()
        legacy = _legacy_reason(stripped, lookup)
        if legacy is not None:
            return legacy
        code = f"RAW_TEXT::{lookup}"
        return make_reason(ReasonCategory.OTHER, code, stripped)
    raise TypeError(f"Unsupported reason type: {type(raw_reason)!r}")


def normalize_reason_list(reasons: Sequence[ReasonLike]) -> list[ReasonDetail]:
    """Normalize a sequence of reason-like values."""

    return [normalize_reason(reason) for reason in reasons]


def dedupe_reasons(reasons: Iterable[ReasonLike]) -> list[ReasonDetail]:
    """Return a list of unique reasons preserving the most recent occurrence."""

    dedup: dict[str, ReasonDetail] = {}
    for reason in reasons:
        detail = normalize_reason(reason)
        dedup[detail.code] = detail
    return list(dedup.values())


_LEGACY_REASON_MAP: MutableMapping[str, ReasonDetail] = {
    "onvoldoende volume/open interest": make_reason(
        ReasonCategory.LOW_LIQUIDITY,
        "LOW_LIQUIDITY_VOLUME",
        "onvoldoende volume/open interest",
    ),
    "onvoldoende volume": make_reason(
        ReasonCategory.LOW_LIQUIDITY,
        "LOW_LIQUIDITY_VOLUME",
        "onvoldoende volume",
    ),
    "liquiditeit onvoldoende": make_reason(
        ReasonCategory.LOW_LIQUIDITY,
        "LOW_LIQUIDITY_GENERIC",
        "liquiditeit onvoldoende",
    ),
    "liquiditeit te laag": make_reason(
        ReasonCategory.LOW_LIQUIDITY,
        "LOW_LIQUIDITY_GENERIC",
        "liquiditeit te laag",
    ),
    "parity via close gebruikt voor midprijs": make_reason(
        ReasonCategory.PREVIEW_QUALITY,
        "PREVIEW_PARITY_CLOSE",
        "previewkwaliteit (parity_close)",
        data={"mid_source": "parity_close"},
    ),
    "fallback naar close gebruikt voor midprijs": make_reason(
        ReasonCategory.PREVIEW_QUALITY,
        "PREVIEW_CLOSE",
        "previewkwaliteit (close)",
        data={"mid_source": "close"},
    ),
    "model-mid gebruikt": make_reason(
        ReasonCategory.PREVIEW_QUALITY,
        "PREVIEW_MODEL",
        "previewkwaliteit (model)",
        data={"mid_source": "model"},
    ),
    "midprijs niet gevonden": make_reason(
        ReasonCategory.MISSING_DATA,
        "MID_MISSING",
        "mid ontbreekt",
    ),
    "geen midprijs beschikbaar": make_reason(
        ReasonCategory.MISSING_DATA,
        "MID_MISSING",
        "mid ontbreekt",
    ),
    "ontbrekende strikes": make_reason(
        ReasonCategory.MISSING_DATA,
        "MISSING_STRIKES",
        "ontbrekende strikes",
    ),
    "opties niet gevonden": make_reason(
        ReasonCategory.MISSING_DATA,
        "OPTIONS_NOT_FOUND",
        "opties niet gevonden",
    ),
    "short opties niet gevonden": make_reason(
        ReasonCategory.MISSING_DATA,
        "OPTIONS_NOT_FOUND",
        "short opties niet gevonden",
    ),
    "short optie ontbreekt": make_reason(
        ReasonCategory.MISSING_DATA,
        "SHORT_OPTION_MISSING",
        "short optie ontbreekt",
    ),
    "long optie ontbreekt": make_reason(
        ReasonCategory.MISSING_DATA,
        "LONG_OPTION_MISSING",
        "long optie ontbreekt",
    ),
    "long strike niet gevonden": make_reason(
        ReasonCategory.MISSING_DATA,
        "LONG_STRIKE_NOT_FOUND",
        "long strike niet gevonden",
    ),
    "center strike niet gevonden": make_reason(
        ReasonCategory.MISSING_DATA,
        "CENTER_STRIKE_NOT_FOUND",
        "center strike niet gevonden",
    ),
    "strike te ver van target": make_reason(
        ReasonCategory.MISSING_DATA,
        "STRIKE_OUT_OF_RANGE",
        "strike te ver van target",
    ),
    "geen expiries beschikbaar": make_reason(
        ReasonCategory.MISSING_DATA,
        "EXPIRY_NOT_AVAILABLE",
        "geen expiries beschikbaar",
    ),
    "risk/reward onvoldoende": make_reason(
        ReasonCategory.RR_BELOW_MIN,
        "RR_TOO_LOW",
        "risk/reward onvoldoende",
    ),
    "negatieve credit": make_reason(
        ReasonCategory.POLICY_VIOLATION,
        "NEGATIVE_CREDIT",
        "negatieve credit",
    ),
    "negatieve ev of score": make_reason(
        ReasonCategory.EV_BELOW_MIN,
        "EV_TOO_LOW",
        "negatieve EV of score",
    ),
    "ongeldige delta range": make_reason(
        ReasonCategory.POLICY_VIOLATION,
        "DELTA_RANGE_INVALID",
        "ongeldige delta range",
    ),
    "ongeldige delta": make_reason(
        ReasonCategory.POLICY_VIOLATION,
        "DELTA_INVALID",
        "ongeldige delta",
    ),
    "verkeerde ratio": make_reason(
        ReasonCategory.POLICY_VIOLATION,
        "RATIO_INVALID",
        "verkeerde ratio",
    ),
    "ontbrekende bid/ask-data": make_reason(
        ReasonCategory.MISSING_DATA,
        "BID_ASK_MISSING",
        "ontbrekende bid/ask-data",
    ),
    "margin kon niet worden berekend": make_reason(
        ReasonCategory.MISSING_DATA,
        "MARGIN_MISSING",
        "margin kon niet worden berekend",
    ),
    "rom kon niet worden berekend omdat margin ontbreekt": make_reason(
        ReasonCategory.MISSING_DATA,
        "ROM_MISSING",
        "ROM kon niet worden berekend omdat margin ontbreekt",
    ),
    "metrics niet berekend": make_reason(
        ReasonCategory.MISSING_DATA,
        "METRICS_MISSING",
        "metrics niet berekend",
    ),
    "parity via close": make_reason(
        ReasonCategory.PREVIEW_QUALITY,
        "PREVIEW_PARITY_CLOSE",
        "previewkwaliteit (parity_close)",
        data={"mid_source": "parity_close"},
    ),
    "fallback naar close": make_reason(
        ReasonCategory.PREVIEW_QUALITY,
        "PREVIEW_CLOSE",
        "previewkwaliteit (close)",
        data={"mid_source": "close"},
    ),
    "model-mid": make_reason(
        ReasonCategory.PREVIEW_QUALITY,
        "PREVIEW_MODEL",
        "previewkwaliteit (model)",
        data={"mid_source": "model"},
    ),
}


__all__: Final[Iterable[str]] = (
    "ReasonCategory",
    "ReasonCategoryLiteral",
    "ReasonDetail",
    "ReasonLike",
    "category_label",
    "category_priority",
    "make_reason",
    "normalize_reason",
    "normalize_reason_list",
    "dedupe_reasons",
    "reason_from_mid_source",
)

