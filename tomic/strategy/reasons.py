"""Utilities for classifying strategy rejection reasons."""

from __future__ import annotations

import re
from enum import Enum
from typing import Final, Iterable, Literal, Sequence


class ReasonCategory(str, Enum):
    """Canonical categories for rejection reasons."""

    LOW_LIQUIDITY = "LOW_LIQUIDITY"
    MISSING_MID = "MISSING_MID"
    MISSING_STRIKES = "MISSING_STRIKES"
    WIDE_SPREAD = "WIDE_SPREAD"
    RULES_FILTER = "RULES_FILTER"
    OTHER = "OTHER"


ReasonCategoryLiteral = Literal[
    "LOW_LIQUIDITY",
    "MISSING_MID",
    "MISSING_STRIKES",
    "WIDE_SPREAD",
    "RULES_FILTER",
    "OTHER",
]

# Mapping of exact (lowercase) reason strings to their canonical category.
_EXACT_REASON_MAP: Final[dict[str, ReasonCategory]] = {
    "onvoldoende volume/open interest": ReasonCategory.LOW_LIQUIDITY,
    "onvoldoende volume": ReasonCategory.LOW_LIQUIDITY,
    "liquiditeit onvoldoende": ReasonCategory.LOW_LIQUIDITY,
    "liquiditeit te laag": ReasonCategory.LOW_LIQUIDITY,
    "fallback naar close gebruikt voor midprijs": ReasonCategory.MISSING_MID,
    "model-mid gebruikt": ReasonCategory.MISSING_MID,
    "parity-mid gebruikt": ReasonCategory.MISSING_MID,
    "midprijs niet gevonden": ReasonCategory.MISSING_MID,
    "geen midprijs beschikbaar": ReasonCategory.MISSING_MID,
    "ontbrekende strikes": ReasonCategory.MISSING_STRIKES,
    "opties niet gevonden": ReasonCategory.MISSING_STRIKES,
    "short opties niet gevonden": ReasonCategory.MISSING_STRIKES,
    "short optie ontbreekt": ReasonCategory.MISSING_STRIKES,
    "long optie ontbreekt": ReasonCategory.MISSING_STRIKES,
    "long strike niet gevonden": ReasonCategory.MISSING_STRIKES,
    "center strike niet gevonden": ReasonCategory.MISSING_STRIKES,
    "strike te ver van target": ReasonCategory.MISSING_STRIKES,
    "geen expiries beschikbaar": ReasonCategory.MISSING_STRIKES,
    "risk/reward onvoldoende": ReasonCategory.RULES_FILTER,
    "negatieve credit": ReasonCategory.RULES_FILTER,
    "negatieve ev of score": ReasonCategory.RULES_FILTER,
    "ongeldige delta range": ReasonCategory.RULES_FILTER,
    "ongeldige delta": ReasonCategory.RULES_FILTER,
    "verkeerde ratio": ReasonCategory.RULES_FILTER,
}

# Fallback substring checks ordered from most to least specific.
_SUBSTRING_RULES: Final[Sequence[tuple[str, ReasonCategory]]] = (
    ("volume", ReasonCategory.LOW_LIQUIDITY),
    ("open interest", ReasonCategory.LOW_LIQUIDITY),
    ("liquiditeit", ReasonCategory.LOW_LIQUIDITY),
    ("midprijs", ReasonCategory.MISSING_MID),
    ("geen mid", ReasonCategory.MISSING_MID),
    ("fallback naar close", ReasonCategory.MISSING_MID),
    ("mid/", ReasonCategory.MISSING_MID),
    ("strike", ReasonCategory.MISSING_STRIKES),
    ("optie", ReasonCategory.MISSING_STRIKES),
    ("expiry", ReasonCategory.MISSING_STRIKES),
    ("expirie", ReasonCategory.MISSING_STRIKES),
    ("spread te", ReasonCategory.WIDE_SPREAD),
    ("bid/ask", ReasonCategory.WIDE_SPREAD),
    ("bid-ask", ReasonCategory.WIDE_SPREAD),
    ("delta", ReasonCategory.RULES_FILTER),
    ("criteria", ReasonCategory.RULES_FILTER),
    ("rules", ReasonCategory.RULES_FILTER),
    ("score", ReasonCategory.RULES_FILTER),
)

# Regex patterns for advanced fallback classification.
_REGEX_RULES: Final[Sequence[tuple[re.Pattern[str], ReasonCategory]]] = (
    (re.compile(r"\bvolume\b|open\s*interest|liquiditeit", re.IGNORECASE), ReasonCategory.LOW_LIQUIDITY),
    (re.compile(r"mid(\b|prijs)|fallback\s+naar\s+close", re.IGNORECASE), ReasonCategory.MISSING_MID),
    (
        re.compile(
            r"(ontbreek|niet\s+gevonden|geen)\s+(strike|optie|expir)"
            r"|strike\s+te\s+ver",
            re.IGNORECASE,
        ),
        ReasonCategory.MISSING_STRIKES,
    ),
    (re.compile(r"spread\s+te\s+(wijd|breed)|\bbid\s*/\s*ask\b", re.IGNORECASE), ReasonCategory.WIDE_SPREAD),
    (
        re.compile(
            r"(risk/?reward|negatieve\s+(ev|credit)|ongeldige\s+delta|rules?\s*filter|criteria)",
            re.IGNORECASE,
        ),
        ReasonCategory.RULES_FILTER,
    ),
)


def _match_exact(reason: str) -> ReasonCategory | None:
    return _EXACT_REASON_MAP.get(reason)


def _match_by_substring(reason: str) -> ReasonCategory | None:
    for needle, category in _SUBSTRING_RULES:
        if needle in reason:
            return category
    return None


def _match_by_regex(reason: str) -> ReasonCategory | None:
    for pattern, category in _REGEX_RULES:
        if pattern.search(reason):
            return category
    return None


_MATCHERS: Final[Sequence] = (
    _match_exact,
    _match_by_substring,
    _match_by_regex,
)


def normalize_reason(raw_reason: str | None) -> ReasonCategory:
    """Map ``raw_reason`` to a canonical :class:`ReasonCategory`."""

    if not raw_reason:
        return ReasonCategory.OTHER
    reason = raw_reason.strip().lower()
    if not reason:
        return ReasonCategory.OTHER

    for matcher in _MATCHERS:
        category = matcher(reason)
        if category is not None:
            return category
    return ReasonCategory.OTHER


__all__: Final[Iterable[str]] = ("ReasonCategory", "ReasonCategoryLiteral", "normalize_reason")
