from tomic.logutils import normalize_reason
from tomic.strategy.reasons import ReasonCategory


def test_normalize_reason_exact_and_casefold():
    detail = normalize_reason("fallback naar close gebruikt voor midprijs")
    assert detail.category == ReasonCategory.PREVIEW_QUALITY
    assert detail.data.get("mid_source") == "close"
    assert normalize_reason("Onvoldoende Volume").category == ReasonCategory.LOW_LIQUIDITY
    assert normalize_reason("Previewkwaliteit").category == ReasonCategory.PREVIEW_QUALITY
    assert normalize_reason(None).category == ReasonCategory.OTHER
