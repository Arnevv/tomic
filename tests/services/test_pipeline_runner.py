from datetime import date

import pytest

from tomic.services.pipeline_runner import PipelineRunContext, run_pipeline
from tomic.services.strategy_pipeline import (
    PipelineRunError,
    RejectionSummary,
)
from tomic.strategy.models import StrategyProposal


class _DummyPipeline:
    def __init__(self):
        self.last_context = None

    def build_proposals(self, context):
        self.last_context = context
        proposal = StrategyProposal(strategy=context.strategy, legs=[{"id": 1}])
        return [proposal], RejectionSummary(by_filter={"dte": 1})


def test_run_pipeline_returns_normalized_result():
    pipeline = _DummyPipeline()
    context = PipelineRunContext(
        pipeline=pipeline,
        symbol="AAA",
        strategy="iron_condor",
        option_chain=[{"expiry": "2024-01-19"}],
        spot_price=123.45,
        atr=1.5,
        config={"threshold": 1},
        interest_rate=0.02,
        dte_range=(10, 25),
        interactive_mode=True,
        criteria={"foo": "bar"},
        next_earnings=date(2024, 6, 1),
    )

    result = run_pipeline(context)

    assert pipeline.last_context is result.context
    assert result.context.symbol == "AAA"
    assert result.context.strategy == "iron_condor"
    assert result.context.dte_range == (10, 25)
    assert result.context.interactive_mode is True
    assert result.proposals and result.proposals[0].strategy == "iron_condor"
    assert isinstance(result.summary, RejectionSummary)
    assert list(result.filtered_chain) == list(result.context.option_chain)


def test_run_pipeline_wraps_pipeline_errors():
    class _FailingPipeline:
        def build_proposals(self, _context):
            raise ValueError("boom")

    context = PipelineRunContext(
        pipeline=_FailingPipeline(),
        symbol="AAA",
        strategy="iron_condor",
        option_chain=[{"expiry": "2024-01-19"}],
        spot_price=120.0,
    )

    with pytest.raises(PipelineRunError) as excinfo:
        run_pipeline(context)

    assert "AAA/iron_condor" in str(excinfo.value)
