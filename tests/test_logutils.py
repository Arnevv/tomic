from tomic.logutils import normalize_reason
from tomic.strategy.reasons import ReasonCategory


def test_normalize_reason_exact_and_casefold():
    assert (
        normalize_reason("fallback naar close gebruikt voor midprijs")
        == ReasonCategory.MISSING_MID
    )
    assert normalize_reason("Onvoldoende Volume") == ReasonCategory.LOW_LIQUIDITY
    assert normalize_reason(None) == ReasonCategory.OTHER
