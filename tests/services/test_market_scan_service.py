from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from tomic.helpers.price_utils import ClosePriceSnapshot
from tomic.services.chain_processing import ChainPreparationConfig, SpotResolution
from tomic.services.market_scan_service import (
    MarketScanError,
    MarketScanRequest,
    MarketScanService,
)
from tomic.services.pipeline_runner import PipelineRunContext
from tomic.services.strategy_pipeline import (
    PipelineRunError,
    PipelineRunResult,
    RejectionSummary,
)
from tomic.strategy.reasons import ReasonCategory, ReasonDetail
from tomic.strategy.models import StrategyContext, StrategyProposal


class _PortfolioStub:
    def rank_candidates(self, rows, _rules):
        return list(rows)


def test_market_scan_service_builds_pipeline_context(monkeypatch, tmp_path):
    contexts: list[PipelineRunContext] = []

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

    monkeypatch.setattr("tomic.services.market_scan_service.run_pipeline", fake_run)
    monkeypatch.setattr(
        "tomic.services.market_scan_service.load_and_prepare_chain",
        lambda *args, **kwargs: SimpleNamespace(records=[{"expiry": "2024-01-19"}]),
    )
    spot_close = ClosePriceSnapshot(99.0, "2024-05-01", "mock", "2024-05-01T10:00:00", True)
    monkeypatch.setattr(
        "tomic.services.market_scan_service.resolve_spot_price",
        lambda *args, **kwargs: SpotResolution(
            price=101.0,
            source="mock",
            is_live=True,
            used_close_fallback=False,
            close=spot_close,
        ),
    )
    monkeypatch.setattr(
        "tomic.services.market_scan_service.load_dte_range", lambda *args, **kwargs: (10, 25)
    )

    pipeline = object()
    service = MarketScanService(
        pipeline,
        _PortfolioStub(),
        interest_rate=0.03,
        strategy_config={"iron_condor": {"foo": "bar"}},
        chain_config=ChainPreparationConfig(min_quality=0),
        refresh_spot_price=lambda symbol: 101.0,
        load_spot_from_metrics=lambda path, symbol: None,
        load_latest_close=lambda symbol: spot_close,
        spot_from_chain=lambda records: 100.0,
        atr_loader=lambda symbol: 2.5,
    )

    chain_path = tmp_path / "AAA.csv"
    chain_path.write_text("symbol,expiry\nAAA,2024-01-19\n")

    requests = [
        MarketScanRequest(
            symbol="AAA",
            strategy="iron_condor",
            metrics={"iv_rank": 0.5},
            next_earnings=date(2024, 6, 1),
        )
    ]

    result = service.run_market_scan(
        requests,
        chain_source=lambda symbol: chain_path,
        top_n=5,
        refresh_quotes=False,
    )

    assert len(result) == 1
    assert len(contexts) == 1
    ctx = contexts[0]
    assert ctx.pipeline is pipeline
    assert ctx.symbol == "AAA"
    assert ctx.strategy == "iron_condor"
    assert ctx.config == {"iron_condor": {"foo": "bar"}}
    assert ctx.interest_rate == 0.03
    assert ctx.dte_range == (10, 25)
    assert ctx.next_earnings == date(2024, 6, 1)
    assert ctx.interactive_mode is False

    evaluations = service.last_scan_results
    assert len(evaluations) == 1
    evaluation = evaluations[0]
    assert evaluation.symbol == "AAA"
    assert evaluation.strategy == "iron_condor"
    assert evaluation.proposal_count == 1


def test_market_scan_service_translates_pipeline_error(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "tomic.services.market_scan_service.run_pipeline",
        lambda context: (_ for _ in ()).throw(PipelineRunError("kaboom")),
    )
    monkeypatch.setattr(
        "tomic.services.market_scan_service.load_and_prepare_chain",
        lambda *args, **kwargs: SimpleNamespace(records=[{"expiry": "2024-01-19"}]),
    )
    spot_close = ClosePriceSnapshot(99.0, "2024-05-01", "mock", "2024-05-01T10:00:00", True)
    monkeypatch.setattr(
        "tomic.services.market_scan_service.resolve_spot_price",
        lambda *args, **kwargs: SpotResolution(
            price=101.0,
            source="mock",
            is_live=True,
            used_close_fallback=False,
            close=spot_close,
        ),
    )
    monkeypatch.setattr(
        "tomic.services.market_scan_service.load_dte_range", lambda *args, **kwargs: (10, 25)
    )

    pipeline = object()
    service = MarketScanService(
        pipeline,
        _PortfolioStub(),
        interest_rate=0.03,
        chain_config=ChainPreparationConfig(min_quality=0),
        refresh_spot_price=lambda symbol: 101.0,
        load_spot_from_metrics=lambda path, symbol: None,
        load_latest_close=lambda symbol: spot_close,
        spot_from_chain=lambda records: 100.0,
    )

    chain_path = tmp_path / "AAA.csv"
    chain_path.write_text("symbol,expiry\nAAA,2024-01-19\n")

    requests = [
        MarketScanRequest(
            symbol="AAA",
            strategy="iron_condor",
            metrics={},
        )
    ]

    with pytest.raises(MarketScanError):
        service.run_market_scan(
            requests,
            chain_source=lambda symbol: chain_path,
        )


def test_market_scan_service_tracks_rejections(monkeypatch, tmp_path):
    def fake_run(context):
        strategy_context = StrategyContext(
            symbol=context.symbol,
            strategy=context.strategy,
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
        summary = RejectionSummary(
            by_strategy={
                context.strategy: [
                    ReasonDetail(
                        category=ReasonCategory.LOW_LIQUIDITY,
                        code="LOW_LIQUIDITY",
                        message="Onvoldoende volume",
                    )
                ]
            },
            by_reason={"LOW_LIQUIDITY": 1},
        )
        return PipelineRunResult(
            context=strategy_context,
            proposals=[],
            summary=summary,
            filtered_chain=list(context.option_chain),
        )

    monkeypatch.setattr("tomic.services.market_scan_service.run_pipeline", fake_run)
    monkeypatch.setattr(
        "tomic.services.market_scan_service.load_and_prepare_chain",
        lambda *args, **kwargs: SimpleNamespace(records=[{"expiry": "2024-01-19"}]),
    )
    spot_close = ClosePriceSnapshot(99.0, "2024-05-01", "mock", "2024-05-01T10:00:00", True)
    monkeypatch.setattr(
        "tomic.services.market_scan_service.resolve_spot_price",
        lambda *args, **kwargs: SpotResolution(
            price=101.0,
            source="mock",
            is_live=True,
            used_close_fallback=False,
            close=spot_close,
        ),
    )
    monkeypatch.setattr(
        "tomic.services.market_scan_service.load_dte_range", lambda *args, **kwargs: (10, 25)
    )

    pipeline = object()
    service = MarketScanService(
        pipeline,
        _PortfolioStub(),
        interest_rate=0.03,
        chain_config=ChainPreparationConfig(min_quality=0),
        refresh_spot_price=lambda symbol: 101.0,
        load_spot_from_metrics=lambda path, symbol: None,
        load_latest_close=lambda symbol: spot_close,
        spot_from_chain=lambda records: 100.0,
    )

    chain_path = tmp_path / "AAA.csv"
    chain_path.write_text("symbol,expiry\nAAA,2024-01-19\n")

    requests = [
        MarketScanRequest(
            symbol="AAA",
            strategy="iron_condor",
            metrics={},
        )
    ]

    result = service.run_market_scan(
        requests,
        chain_source=lambda symbol: chain_path,
    )

    assert result == []
    evaluations = service.last_scan_results
    assert len(evaluations) == 1
    evaluation = evaluations[0]
    assert evaluation.symbol == "AAA"
    assert evaluation.strategy == "iron_condor"
    assert evaluation.proposal_count == 0
    assert evaluation.summary is not None
    assert evaluation.summary.by_reason["LOW_LIQUIDITY"] == 1
