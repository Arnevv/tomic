from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from tomic.services.market_snapshot_service import (
    MarketSnapshotError,
    MarketSnapshotRow,
    MarketSnapshotService,
    ScanRequest,
    _read_metrics,
)
from tomic.services.pipeline_runner import PipelineRunContext
from tomic.services.strategy_pipeline import (
    PipelineRunError,
    PipelineRunResult,
    RejectionSummary,
)
from tomic.services.portfolio_service import PortfolioService
from tomic.strategy.models import StrategyContext, StrategyProposal


class _PipelineStub:
    def build_proposals(self, context):  # pragma: no cover - stub
        return [], RejectionSummary()


def _loader(path: Path):
    return json.loads(path.read_text())


def test_read_metrics_returns_row(tmp_path):
    summary_dir = tmp_path / "summary"
    hv_dir = tmp_path / "hv"
    spot_dir = tmp_path / "spot"
    for directory in (summary_dir, hv_dir, spot_dir):
        directory.mkdir()

    (summary_dir / "AAA.json").write_text(
        json.dumps(
            [
                {
                    "date": "2024-05-02",
                    "atm_iv": 0.4,
                    "iv_rank (HV)": 62,
                    "iv_percentile (HV)": 75,
                    "term_m1_m2": 1.1,
                    "term_m1_m3": 1.2,
                    "skew": 3.5,
                }
            ]
        )
    )
    (hv_dir / "AAA.json").write_text(
        json.dumps(
            [
                {
                    "date": "2024-05-02",
                    "hv20": 0.2,
                    "hv30": 0.25,
                    "hv90": 0.28,
                    "hv252": 0.3,
                }
            ]
        )
    )
    (spot_dir / "AAA.json").write_text(
        json.dumps(
            [
                {
                    "date": "2024-05-02",
                    "close": 123.4,
                }
            ]
        )
    )

    row = _read_metrics(
        "AAA",
        summary_dir,
        hv_dir,
        spot_dir,
        {"AAA": ["2024-05-10", "2024-04-01"]},
        loader=_loader,
        today_fn=lambda: date(2024, 5, 1),
    )

    assert isinstance(row, MarketSnapshotRow)
    assert row.symbol == "AAA"
    assert row.iv_rank == 0.62
    assert row.iv_percentile == 0.75
    assert row.next_earnings == date(2024, 5, 10)
    assert row.days_until_earnings == 9


def test_build_factsheet_parses_dates():
    service = PortfolioService(today_fn=lambda: date(2024, 5, 20))
    factsheet = service.build_factsheet(
        {
            "symbol": "AAA",
            "strategy": "short_put_spread",
            "spot": 101.2,
            "iv": 0.4,
            "hv20": 0.2,
            "hv30": 0.25,
            "hv90": 0.3,
            "hv252": 0.31,
            "term_m1_m2": 1.1,
            "term_m1_m3": 1.3,
            "iv_rank": 48,
            "iv_percentile": 60,
            "skew": 3.5,
            "criteria": "some,criteria",
            "next_earnings": "2024-06-01",
        },
    )

    assert factsheet.symbol == "AAA"
    assert factsheet.strategy == "short_put_spread"
    assert factsheet.iv_rank == 0.48
    assert factsheet.iv_percentile == 0.60
    assert factsheet.next_earnings == date(2024, 6, 1)
    assert factsheet.days_until_earnings == 12


def test_load_snapshot_returns_serializable_rows(tmp_path):
    summary_dir = tmp_path / "summary"
    hv_dir = tmp_path / "hv"
    spot_dir = tmp_path / "spot"
    for directory in (summary_dir, hv_dir, spot_dir):
        directory.mkdir()

    def write(symbol: str, summary_iv: float, percentile: float):
        (summary_dir / f"{symbol}.json").write_text(
            json.dumps(
                [
                    {
                        "date": "2024-05-02",
                        "atm_iv": summary_iv,
                        "iv_rank (HV)": 55,
                        "iv_percentile (HV)": percentile,
                        "term_m1_m2": 1.1,
                        "term_m1_m3": 1.2,
                        "skew": 3.0,
                    }
                ]
            )
        )
        (hv_dir / f"{symbol}.json").write_text(
            json.dumps(
                [
                    {
                        "date": "2024-05-02",
                        "hv20": 0.2,
                        "hv30": 0.25,
                        "hv90": 0.28,
                        "hv252": 0.3,
                    }
                ]
            )
        )
        (spot_dir / f"{symbol}.json").write_text(
            json.dumps(
                [
                    {
                        "date": "2024-05-02",
                        "close": 120.0,
                    }
                ]
            )
        )

    write("AAA", 0.4, 70)
    write("BBB", 0.3, 40)

    earnings = tmp_path / "earnings.json"
    earnings.write_text(json.dumps({"AAA": ["2024-06-01"], "BBB": ["2024-07-01"]}))

    config = {
        "DEFAULT_SYMBOLS": ["AAA", "BBB"],
        "IV_DAILY_SUMMARY_DIR": str(summary_dir),
        "HISTORICAL_VOLATILITY_DIR": str(hv_dir),
        "PRICE_HISTORY_DIR": str(spot_dir),
        "EARNINGS_DATES_FILE": str(earnings),
    }

    service = MarketSnapshotService(config, loader=_loader, today_fn=lambda: date(2024, 5, 20))
    snapshot = service.load_snapshot()

    assert snapshot.generated_at == date(2024, 5, 20)
    rows = snapshot.rows
    assert [row.symbol for row in rows] == ["AAA", "BBB"]
    assert rows[0].iv_percentile == 0.70
    assert rows[0].next_earnings == date(2024, 6, 1)
    assert rows[0].days_until_earnings == 12

    filtered = service.load_snapshot({"symbols": ["BBB"]})
    assert [row.symbol for row in filtered.rows] == ["BBB"]


def test_scan_symbols_builds_pipeline_context(monkeypatch):
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

    monkeypatch.setattr("tomic.services.market_snapshot_service.run_pipeline", fake_run)

    service = MarketSnapshotService({}, loader=lambda path: {}, today_fn=lambda: date(2024, 5, 1))
    request = ScanRequest(
        symbol="AAA",
        strategy="iron_condor",
        option_chain=[{"expiry": "2024-01-19"}],
        spot_price=101.0,
        atr=1.5,
        config={"foo": "bar"},
        interest_rate=0.02,
        dte_range=(10, 25),
        interactive_mode=True,
        next_earnings=date(2024, 6, 1),
        metrics={"iv_rank": 0.5},
    )

    rows = service.scan_symbols([request], rules={"pipeline": _PipelineStub()})

    assert len(rows) == 1
    assert len(contexts) == 1
    ctx = contexts[0]
    assert ctx.symbol == "AAA"
    assert ctx.strategy == "iron_condor"
    assert list(ctx.option_chain) == [{"expiry": "2024-01-19"}]
    assert ctx.spot_price == 101.0
    assert ctx.atr == 1.5
    assert ctx.config == {"foo": "bar"}
    assert ctx.interest_rate == 0.02
    assert ctx.dte_range == (10, 25)
    assert ctx.interactive_mode is True
    assert ctx.next_earnings == date(2024, 6, 1)


def test_scan_symbols_translates_pipeline_error(monkeypatch):
    monkeypatch.setattr(
        "tomic.services.market_snapshot_service.run_pipeline",
        lambda context: (_ for _ in ()).throw(PipelineRunError("kaboom")),
    )

    service = MarketSnapshotService({}, loader=lambda path: {}, today_fn=lambda: date(2024, 5, 1))
    request = ScanRequest(
        symbol="AAA",
        strategy="iron_condor",
        option_chain=[{"expiry": "2024-01-19"}],
        spot_price=101.0,
        atr=1.5,
        config={},
        interest_rate=0.02,
        dte_range=(10, 25),
        interactive_mode=False,
        next_earnings=None,
        metrics={},
    )

    with pytest.raises(MarketSnapshotError):
        service.scan_symbols([request], rules={"pipeline": _PipelineStub()})
