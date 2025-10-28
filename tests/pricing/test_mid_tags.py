from dataclasses import dataclass

from tomic.core.pricing.mid_service import resolve_option_mid
from tomic.core.pricing.mid_tags import MidTagSnapshot, normalize_mid_source
from tomic.metrics import iter_leg_views
from tomic.mid_resolver import MidUsageSummary


def test_normalize_mid_source_with_fallback_chain():
    leg = {
        "mid": 1.25,
        "mid_source": " Parity ",
        "mid_fallback": " close ",
        "bid": 1.2,
        "ask": 1.3,
        "position": -1,
    }

    normalized = normalize_mid_source(leg["mid_source"], (leg["mid_fallback"],))
    assert normalized == "parity_true"

    quote = resolve_option_mid(leg)
    assert quote.mid_source == "parity_true"

    summary = MidUsageSummary.from_legs([leg])
    assert summary.fallback_summary["parity_true"] == 1

    leg_view = next(iter_leg_views([leg]))
    assert leg_view.mid_source == "parity_true"


def test_mid_usage_prefers_resolver_fallback():
    @dataclass
    class _Resolution:
        mid_source: str | None = None
        mid_fallback: str | None = "parity_close"
        mid: float | None = None
        mid_reason: str | None = None
        spread_flag: str | None = None
        quote_age_sec: float | None = None
        one_sided: bool = False

    class _Resolver:
        def __init__(self) -> None:
            self._resolution = _Resolution()

        def resolution_for(self, leg):  # pragma: no cover - simple stub
            return self._resolution

        def max_fallback_legs(self, count: int) -> int:
            return 0

    summary = MidUsageSummary.from_legs([{"mid_source": "true"}], resolver=_Resolver())
    assert summary.fallback_summary["parity_close"] == 1

    snapshot = MidTagSnapshot(tags=("tradable",), counters=summary.fallback_summary)
    counts = dict(snapshot.counter_items())
    assert counts["parity_close"] == 1
