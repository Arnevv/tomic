from __future__ import annotations

from math import isclose
from types import SimpleNamespace

import pytest

from tomic.services.strategy_pipeline import (
    StrategyPipeline,
    StrategyContext,
    StrategyProposal,
)


class DummySelector:
    def __init__(self, *args, selected=None, by_reason=None, by_filter=None, **kwargs):
        self._selected = selected
        self._by_reason = by_reason or {}
        self._by_filter = by_filter or {}

    def select(self, options, *, dte_range=None, debug_csv=None, return_info=False):
        selected = options if self._selected is None else self._selected
        if return_info:
            return list(selected), dict(self._by_reason), dict(self._by_filter)
        return list(selected)


@pytest.fixture
def sample_option() -> dict:
    return {
        "expiry": "2024-01-19",
        "strike": 100.0,
        "type": "call",
        "bid": 1.0,
        "ask": 1.2,
        "delta": 0.3,
        "marginreq": 250.0,
        "modelprice": 1.1,
    }


def test_build_proposals_generates_results(sample_option):
    selector = DummySelector(selected=[sample_option])

    def selector_factory(**kwargs):
        return selector

    generated = SimpleNamespace(
        legs=[{"strike": 100.0, "type": "call", "position": -1, "edge": 0.5}],
        score=2.4,
        pos=55.0,
        ev=1.2,
        ev_pct=None,
        rom=10.0,
        edge=0.5,
        credit=100.0,
        margin=400.0,
        max_profit=120.0,
        max_loss=280.0,
        breakevens=[95.0],
        fallback=None,
        profit_estimated=False,
        scenario_info={"scenario_label": "base"},
    )

    def generator(symbol, strategy, option_chain, atr, config, spot, interactive_mode=False):
        assert symbol == "XYZ"
        assert strategy == "iron_condor"
        assert option_chain == [sample_option]
        assert isclose(atr, 1.5)
        assert isclose(spot, 102.0)
        assert interactive_mode is True
        return [generated], ["edge:low"]

    pipeline = StrategyPipeline(
        config={"INTEREST_RATE": 0.03},
        market_provider=None,
        strike_selector_factory=selector_factory,
        strategy_generator=generator,
    )

    context = StrategyContext(
        symbol="XYZ",
        strategy="Iron Condor",
        option_chain=[sample_option],
        spot_price=102.0,
        atr=1.5,
        config={"default": {}},
        interactive_mode=True,
        dte_range=(0, 365),
    )

    proposals, summary = pipeline.build_proposals(context)

    assert len(proposals) == 1
    prop = proposals[0]
    assert isinstance(prop, StrategyProposal)
    assert prop.strategy == "iron_condor"
    assert isclose(prop.score or 0.0, 2.4)
    assert prop.legs[0]["strike"] == 100.0
    assert summary.by_strategy == {"iron_condor": ["edge:low"]}
    assert summary.by_filter == {}
    assert pipeline.last_evaluated
    evaluated = pipeline.last_evaluated[0]
    assert isclose(evaluated["mid"], 1.1)
    assert evaluated["rom"] is not None and evaluated["rom"] > 0


def test_build_proposals_handles_rejections(sample_option):
    selector = DummySelector(selected=[], by_filter={"delta": 2}, by_reason={"delta:low": 2})

    def selector_factory(**kwargs):
        return selector

    pipeline = StrategyPipeline(
        config=None,
        market_provider=None,
        strike_selector_factory=selector_factory,
        strategy_generator=lambda *args, **kwargs: ([], []),
    )

    context = StrategyContext(
        symbol="XYZ",
        strategy="iron_condor",
        option_chain=[sample_option],
        spot_price=0.0,
        atr=0.0,
        config={},
        interactive_mode=False,
    )

    proposals, summary = pipeline.build_proposals(context)

    assert proposals == []
    assert summary.by_filter == {"delta": 2}
    assert summary.by_reason == {"delta:low": 2}
    assert summary.by_strategy == {}
    assert pipeline.last_evaluated == []


def test_summarize_rejections_merges():
    pipeline = StrategyPipeline(config=None, market_provider=None)
    data = {
        "by_filter": {"delta": 1},
        "by_reason": {"delta:low": 1},
        "by_strategy": {"iron_condor": ["delta:low"]},
    }
    summary = pipeline.summarize_rejections(data)
    assert summary.by_filter == {"delta": 1}
    assert summary.by_reason == {"delta:low": 1}
    assert summary.by_strategy == {"iron_condor": ["delta:low"]}
