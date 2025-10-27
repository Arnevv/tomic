from types import SimpleNamespace

from tomic.analysis.proposal_engine import (
    generate_proposals,
    suggest_strategies,
)
from tomic.criteria import RULES
from tomic.strategy.models import StrategyProposal
from tomic.strategies import StrategyName


def _make_proposal(strategy: str) -> StrategyProposal:
    legs = [
        {
            "delta": -0.2,
            "gamma": 0.01,
            "vega": -0.4,
            "theta": 0.05,
            "position": -1,
        },
        {
            "delta": 0.1,
            "gamma": -0.005,
            "vega": 0.15,
            "theta": 0.02,
            "position": 1,
        },
    ]
    return StrategyProposal(
        strategy=strategy,
        legs=legs,
        score=75.0,
        rom=12.5,
        risk_reward=1.8,
        margin=450.0,
        max_profit=150.0,
        max_loss=-80.0,
        credit=1.5,
        profit_estimated=False,
        scenario_info={"preferred_move": "flat"},
    )


def test_suggest_strategies_picks_vertical(monkeypatch):
    recorded = []

    def fake_run(ctx, strategy):  # type: ignore[unused-arg]
        recorded.append(strategy)
        return [_make_proposal(str(strategy))]

    monkeypatch.setattr("tomic.analysis.proposal_engine._run_strategy_pipeline", fake_run)
    pipeline = object()
    exposure = {"Delta": 60.0, "Vega": 0.0}
    chain = [{"expiry": "2025-01-01"}]

    result = suggest_strategies(
        "XYZ",
        chain,
        exposure,
        pipeline=pipeline,  # type: ignore[arg-type]
        spot_price=100.0,
        strategy_config={},
        interest_rate=0.05,
    )

    assert recorded == [StrategyName.SHORT_CALL_SPREAD]
    assert result[0]["strategy"] == "short_call_spread"
    assert result[0]["reason"] == "Delta-balancering"
    assert result[0]["impact"]["Delta"] != 0.0
    assert result[0]["score"] == 75.0


def test_suggest_strategies_respects_condor_gate(monkeypatch):
    called = []

    def fake_run(ctx, strategy):  # type: ignore[unused-arg]
        called.append(strategy)
        return [_make_proposal("iron_condor")]

    monkeypatch.setattr("tomic.analysis.proposal_engine._run_strategy_pipeline", fake_run)

    metrics = SimpleNamespace(iv_rank=0.0)
    exposure = {"Delta": 0.0, "Vega": RULES.portfolio.vega_to_condor + 10}
    chain = [{"expiry": "2025-01-01"}]

    result = suggest_strategies(
        "XYZ",
        chain,
        exposure,
        pipeline=object(),  # type: ignore[arg-type]
        spot_price=100.0,
        strategy_config={},
        interest_rate=0.05,
        metrics=metrics,
    )

    # iv_rank below minimum should block the condor suggestion
    assert called == []
    assert result == []


def test_suggest_strategies_respects_calendar_gate(monkeypatch):
    called = []

    def fake_run(ctx, strategy):  # type: ignore[unused-arg]
        called.append(strategy)
        return [_make_proposal("calendar")]

    monkeypatch.setattr("tomic.analysis.proposal_engine._run_strategy_pipeline", fake_run)

    metrics = SimpleNamespace(iv_rank=5.0)
    exposure = {"Delta": 0.0, "Vega": RULES.portfolio.vega_to_calendar - 10}
    chain = [{"expiry": "2025-01-01"}]

    result = suggest_strategies(
        "XYZ",
        chain,
        exposure,
        pipeline=object(),  # type: ignore[arg-type]
        spot_price=100.0,
        strategy_config={},
        interest_rate=0.05,
        metrics=metrics,
    )

    # iv_rank above maximum should block the calendar suggestion
    assert called == []
    assert result == []


def test_generate_proposals_aggregates_pipeline(monkeypatch):
    positions = [{"symbol": "XYZ", "position": 1}]
    exposures = {"XYZ": {"Delta": 60.0, "Vega": 0.0}}

    monkeypatch.setattr(
        "tomic.analysis.proposal_engine.load_json",
        lambda path: positions,
    )
    monkeypatch.setattr(
        "tomic.analysis.proposal_engine.compute_greeks_by_symbol",
        lambda records: exposures,
    )
    monkeypatch.setattr(
        "tomic.analysis.proposal_engine._load_chain_for_symbol",
        lambda _dir, _sym, _cfg: SimpleNamespace(records=[{"expiry": "2025-01-01"}], quality=100),
    )
    monkeypatch.setattr(
        "tomic.analysis.proposal_engine.StrategyPipeline",
        lambda *a, **k: object(),
    )
    monkeypatch.setattr(
        "tomic.analysis.proposal_engine._run_strategy_pipeline",
        lambda ctx, strategy: [_make_proposal(str(strategy))],
    )

    proposals = generate_proposals("positions.json", "chains")

    assert "XYZ" in proposals
    assert proposals["XYZ"][0]["strategy"] == "short_call_spread"

