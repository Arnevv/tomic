"""Common strategy identifiers used across the project."""

from enum import Enum


class StrategyName(str, Enum):
    """Supported strategy identifiers.

    The value of each member is the canonical string representation used
    throughout the codebase. The enum derives from ``str`` so members can be
    used interchangeably where a string is expected.
    """

    SHORT_PUT_SPREAD = "short_put_spread"
    SHORT_CALL_SPREAD = "short_call_spread"
    IRON_CONDOR = "iron_condor"
    ATM_IRON_BUTTERFLY = "atm_iron_butterfly"
    NAKED_PUT = "naked_put"
    CALENDAR = "calendar"
    BACKSPREAD_PUT = "backspread_put"
    RATIO_SPREAD = "ratio_spread"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return str(self.value)

    def __format__(self, format_spec: str) -> str:  # pragma: no cover - trivial
        return format(str(self.value), format_spec)


__all__ = ["StrategyName"]

