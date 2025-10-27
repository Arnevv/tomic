import pytest

from tomic.mid_resolver import MidUsageSummary
from tomic.strategy.reason_engine import ReasonEngine


@pytest.mark.parametrize(
    "legs, fallback_allowed, expected_status, expected_tags",
    [
        ([{"mid_source": "true", "position": -1, "mid": 1.0}], 2, "tradable", ("tradable", "true:1")),
        (
            [{"mid_source": "close", "position": -1, "mid": 1.0}],
            4,
            "advisory",
            ("advisory", "needs_refresh", "close:1"),
        ),
    ],
)
def test_reason_engine_basic_status(legs, fallback_allowed, expected_status, expected_tags):
    summary = MidUsageSummary.from_legs(legs, fallback_allowed=fallback_allowed)
    evaluation = ReasonEngine().evaluate(summary)
    assert evaluation.status == expected_status
    assert evaluation.needs_refresh == ("needs_refresh" in expected_tags)
    assert evaluation.tags == expected_tags
    assert tuple(sorted(evaluation.fallback_summary)) == tuple(sorted(summary.fallback_summary))


def test_reason_engine_preview_reasons():
    summary = MidUsageSummary.from_legs(
        [{"mid_source": "close", "position": -1, "mid": 1.0}],
        fallback_allowed=4,
    )
    evaluation = ReasonEngine().evaluate(summary)
    codes = {detail.code for detail in evaluation.reasons}
    assert "PREVIEW_close" in codes
    assert evaluation.preview_sources == ("close",)
    assert evaluation.needs_refresh is True


def test_reason_engine_rejected_on_spread_and_limit():
    legs = [
        {"mid_source": "model", "position": -1, "spread_flag": "too_wide", "mid": 1.0},
        {"mid_source": "model", "position": 1, "mid": 1.0},
    ]
    summary = MidUsageSummary.from_legs(legs, fallback_allowed=0)
    engine = ReasonEngine()
    evaluation = engine.evaluate(summary)
    codes = {detail.code for detail in evaluation.reasons}
    assert evaluation.status == "rejected"
    assert evaluation.fallback_limit_exceeded is True
    assert "MID_SPREAD_WIDE" in codes
    assert "MID_FALLBACK_LIMIT" in codes
    assert evaluation.needs_refresh is True
    assert any(tag.startswith("spread_wide:") for tag in evaluation.tags)
