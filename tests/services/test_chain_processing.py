from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from tomic.services.chain_processing import (
    ChainPreparationError,
    ChainPreparationConfig,
    ChainEvaluationConfig,
    PreparedChain,
    evaluate_chain,
    load_and_prepare_chain,
)
from tomic.services.pipeline_runner import PipelineRunContext, run_pipeline
from tomic.services.strategy_pipeline import (
    PipelineRunError,
    PipelineRunResult,
    RejectionSummary,
    StrategyContext,
    StrategyProposal,
)


if not hasattr(pd, "DataFrame") or isinstance(pd.DataFrame, type(object)):
    pytest.skip("pandas not available", allow_module_level=True)


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    pd.DataFrame(rows).to_csv(path, index=False)


def test_load_and_prepare_chain_normalizes_values(tmp_path):
    csv_path = tmp_path / "chain.csv"
    _write_csv(
        csv_path,
        [
            {
                "Expiration": "2024-01-19",
                "BID": "1,20",
                "Ask": "1,50",
                "Delta": "0,45",
                "Gamma": "0,10",
                "Vega": "0,25",
                "Theta": "-0,05",
                "Strike": 100,
                "Type": "CALL",
            },
            {
                "Expiration": "2024-02-16",
                "BID": "",
                "Ask": "1,55",
                "Delta": "",
                "Gamma": "",
                "Vega": "",
                "Theta": "",
                "Strike": 105,
                "Type": "PUT",
            },
        ],
    )

    config = ChainPreparationConfig(min_quality=0)
    prepared = load_and_prepare_chain(csv_path, config)

    assert isinstance(prepared, PreparedChain)
    assert prepared.path == csv_path
    first = prepared.records[0]
    assert first["bid"] == pytest.approx(1.20)
    assert first["ask"] == pytest.approx(1.50)
    assert first["delta"] == pytest.approx(0.45)
    assert first["expiry"] == "2024-01-19"
    second = prepared.records[1]
    assert second["bid"] is None
    assert second["delta"] is None
    assert second["expiry"] == "2024-02-16"


class _DummyPipeline:
    def __init__(self):
        self.last_context = None

    def build_proposals(self, context):
        self.last_context = context
        return [], RejectionSummary()


def test_load_and_prepare_chain_integrates_with_pipeline(tmp_path):
    csv_path = tmp_path / "chain.csv"
    _write_csv(
        csv_path,
        [
            {
                "expiration": "2024-01-19",
                "bid": "1,10",
                "ask": "1,20",
                "delta": "0,40",
                "gamma": "0,05",
                "vega": "0,10",
                "theta": "-0,04",
                "strike": 100,
                "type": "CALL",
            }
        ],
    )

    config = ChainPreparationConfig(min_quality=0)
    prepared = load_and_prepare_chain(csv_path, config)

    pipeline = _DummyPipeline()
    context = PipelineRunContext(
        pipeline=pipeline,
        symbol="AAA",
        strategy="iron_condor",
        option_chain=prepared.records,
        spot_price=100.0,
        atr=1.5,
        config={},
        interest_rate=0.01,
    )
    result = run_pipeline(context)

    assert result.context.symbol == "AAA"
    assert pipeline.last_context is result.context
    assert len(result.filtered_chain) == 1
    record = pipeline.last_context.option_chain[0]
    assert record["bid"] == pytest.approx(1.10)
    assert record["delta"] == pytest.approx(0.40)
    assert record["expiry"] == "2024-01-19"


def test_evaluate_chain_builds_pipeline_context(monkeypatch, tmp_path):
    contexts = []

    def fake_run(context):
        contexts.append(context)
        strategy_context = StrategyContext(
            symbol=context.symbol,
            strategy=str(context.strategy),
            option_chain=list(context.option_chain),
            spot_price=context.spot_price,
            atr=context.atr,
            config=context.config,
            interest_rate=context.interest_rate,
            dte_range=context.dte_range,
            interactive_mode=context.interactive_mode,
            criteria=context.criteria,
            next_earnings=context.next_earnings,
            debug_path=context.debug_path,
        )
        proposal = StrategyProposal(strategy=str(context.strategy), legs=[{"id": 1}])
        return PipelineRunResult(
            context=strategy_context,
            proposals=[proposal],
            summary=RejectionSummary(),
            filtered_chain=list(context.option_chain),
        )

    monkeypatch.setattr("tomic.services.chain_processing.run_pipeline", fake_run)

    prepared = SimpleNamespace(records=[{"expiry": "2024-01-19"}, {"expiry": "2024-02-16"}])
    config = ChainEvaluationConfig(
        symbol="AAA",
        strategy="iron_condor",
        strategy_config={"foo": "bar"},
        interest_rate=0.02,
        export_dir=tmp_path,
        dte_range=(10, 25),
        spot_price=123.4,
        atr=1.2,
        interactive_mode=True,
        debug_filename="chain.csv",
    )

    pipeline = object()
    result = evaluate_chain(prepared, pipeline, config)

    assert len(contexts) == 1
    ctx = contexts[0]
    assert ctx.pipeline is pipeline
    assert ctx.symbol == "AAA"
    assert ctx.strategy == "iron_condor"
    assert list(ctx.option_chain) == list(prepared.records)
    assert ctx.spot_price == pytest.approx(123.4)
    assert ctx.atr == pytest.approx(1.2)
    assert ctx.config == {"foo": "bar"}
    assert ctx.interest_rate == pytest.approx(0.02)
    assert ctx.dte_range == (10, 25)
    assert ctx.interactive_mode is True
    assert ctx.debug_path == tmp_path / "chain.csv"
    assert result.proposals and result.proposals[0].strategy == "iron_condor"


def test_evaluate_chain_translates_pipeline_error(monkeypatch, tmp_path):
    def fake_run(_context):
        raise PipelineRunError("boom")

    monkeypatch.setattr("tomic.services.chain_processing.run_pipeline", fake_run)

    prepared = SimpleNamespace(records=[{"expiry": "2024-01-19"}])
    config = ChainEvaluationConfig(
        symbol="AAA",
        strategy="iron_condor",
        strategy_config={},
        interest_rate=0.01,
        export_dir=tmp_path,
        dte_range=(10, 20),
        spot_price=100.0,
        atr=1.0,
    )

    with pytest.raises(ChainPreparationError):
        evaluate_chain(prepared, object(), config)
