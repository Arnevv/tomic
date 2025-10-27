from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from tomic.cli.app_services import ControlPanelServices, ExportServices
from tomic.cli.controlpanel_session import ControlPanelSession
from tomic.cli.portfolio import menu_flow
from tomic.helpers.price_utils import ClosePriceSnapshot
from tomic.services.chain_processing import SpotResolution


@pytest.fixture
def services() -> ControlPanelServices:
    pipeline_mock = mock.Mock()
    export = ExportServices(
        export_chain=lambda *args, **kwargs: None,
        fetch_polygon_chain=lambda symbol: Path(f"{symbol}.csv"),
        find_latest_chain=lambda *args, **kwargs: None,
        git_commit=lambda *args, **kwargs: False,
    )
    svc = ControlPanelServices(
        pipeline_factory=lambda: pipeline_mock,
        market_snapshot=mock.Mock(),
        portfolio=mock.Mock(),
        export=export,
    )
    svc._pipeline = pipeline_mock
    return svc


def test_process_chain_evaluates_and_updates_session(
    services: ControlPanelServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = ControlPanelSession(symbol="SPY", strategy="Short Put")

    prep_config = SimpleNamespace(min_quality=90.0)
    monkeypatch.setattr(
        menu_flow.ChainPreparationConfig,
        "from_app_config",
        classmethod(lambda cls: prep_config),
    )

    prepared = SimpleNamespace(quality=95.0, records=[{"dummy": True}])
    monkeypatch.setattr(
        menu_flow,
        "load_and_prepare_chain",
        lambda path, config, apply_interpolation=False: prepared,
    )
    monkeypatch.setattr(
        menu_flow,
        "resolve_chain_spot_price",
        lambda *a, **k: SpotResolution(101.0, "live", True, False),
    )
    monkeypatch.setattr(
        menu_flow.ChainEvaluationConfig,
        "from_app_config",
        classmethod(lambda cls, **kwargs: SimpleNamespace(**kwargs)),
    )
    monkeypatch.setattr(menu_flow, "latest_atr", lambda symbol: 1.5)

    proposal = SimpleNamespace(
        legs=[
            {
                "position": 1,
                "type": "P",
                "strike": 100,
                "expiry": "2024-06-21",
                "edge": 0.2,
            }
        ],
        ev=1.25,
        rom=2.5,
        score=3.0,
        pos=55.0,
        profit_estimated=False,
        scenario_info={},
    )

    evaluation = SimpleNamespace(
        context=SimpleNamespace(symbol="SPY", spot_price=101.0),
        filter_preview=SimpleNamespace(),
        evaluated_trades=[
            {
                "expiry": "2024-06-21",
                "strike": 100,
                "type": "P",
                "delta": -0.3,
                "edge": 0.1,
                "pos": 60.0,
            }
        ],
        proposals=[proposal],
        summary=SimpleNamespace(),
    )
    monkeypatch.setattr(menu_flow, "evaluate_chain", lambda prepared, pipeline, config: evaluation)

    yes_no_answers = iter([True, False, False, True])

    def prompt_yes_no(message: str, default: bool) -> bool:
        return next(yes_no_answers)

    prompt_calls: list[str] = []

    def prompt_fn(message: str) -> str:
        prompt_calls.append(message)
        return "0"

    tabulate_calls: list[tuple[list[list[object]], dict[str, object]]] = []

    def tabulate_fn(rows, **kwargs):
        tabulate_calls.append((list(rows), dict(kwargs)))
        return "table"

    build_rejection_summary = mock.Mock()
    save_trades = mock.Mock()
    print_overview = mock.Mock()

    refresh_spot = mock.Mock(return_value=110.0)

    result = menu_flow.process_chain(
        session,
        services,
        Path("dummy.csv"),
        False,
        tabulate_fn=tabulate_fn,
        prompt_fn=prompt_fn,
        prompt_yes_no_fn=prompt_yes_no,
        show_proposal_details=mock.Mock(),
        build_rejection_summary_fn=build_rejection_summary,
        save_trades_fn=save_trades,
        refresh_spot_price_fn=refresh_spot,
        load_spot_from_metrics_fn=mock.Mock(return_value=None),
        load_latest_close_fn=mock.Mock(return_value=ClosePriceSnapshot(120.0, "2024-05-01")),
        spot_from_chain_fn=mock.Mock(return_value=102.0),
        print_evaluation_overview_fn=print_overview,
    )

    assert result is True
    assert session.evaluated_trades == evaluation.evaluated_trades
    assert session.spot_price == 110.0
    assert evaluation.context.spot_price == 110.0
    assert build_rejection_summary.call_count == 2
    assert build_rejection_summary.call_args_list[0].kwargs["show_reasons"] is False
    assert build_rejection_summary.call_args_list[1].kwargs["show_reasons"] is True
    save_trades.assert_not_called()
    print_overview.assert_called_once()
    refresh_spot.assert_called_once_with("SPY")
    assert prompt_calls[-1] == "Kies voorstel (0 om terug): "
    assert tabulate_calls, "Tabulate should be invoked for trade/proposal tables"


def test_run_market_scan_selects_candidate(
    services: ControlPanelServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = ControlPanelSession()

    config_values = {
        "MARKET_SCAN_TOP_N": 3,
        "STRATEGY_CONFIG": {"dummy": True},
        "INTEREST_RATE": 0.05,
    }

    def fake_get(key: str, default=None):
        return config_values.get(key, default)

    monkeypatch.setattr(menu_flow.cfg, "get", fake_get)
    monkeypatch.setattr(
        menu_flow.ChainPreparationConfig,
        "from_app_config",
        classmethod(lambda cls: SimpleNamespace()),
    )

    scan_service = mock.Mock()
    monkeypatch.setattr(menu_flow, "MarketScanService", mock.Mock(return_value=scan_service))

    proposal = SimpleNamespace(
        legs=[{"expiry": "2024-06-21", "type": "P", "strike": 100, "edge": 0.1}],
        ev=1.0,
        rom=2.0,
        score=3.0,
        pos=60.0,
        profit_estimated=False,
        scenario_info={},
    )
    candidate = SimpleNamespace(
        symbol="SPY",
        strategy="short_put",
        proposal=proposal,
        risk_reward=1.5,
        dte_summary="30",
        iv_rank=0.4,
        skew=0.1,
        bid_ask_pct=0.02,
        mid_sources=("tradable", "true:1"),
        mid_status="tradable",
        needs_refresh=False,
        next_earnings=None,
        spot=105.0,
    )
    scan_service.run_market_scan.return_value = [candidate]

    prompt_values = iter(["", "1", "0"])

    def prompt_fn(message: str) -> str:
        return next(prompt_values)

    prompt_yes_no_calls: list[tuple[str, bool]] = []

    def prompt_yes_no_fn(message: str, default: bool) -> bool:
        prompt_yes_no_calls.append((message, default))
        return True

    tabulate_calls = []

    def tabulate_fn(rows, **kwargs):
        tabulate_calls.append((rows, kwargs))
        return "table"

    show_details = mock.Mock()

    menu_flow.run_market_scan(
        session,
        services,
        [
            {
                "symbol": "SPY",
                "strategy": "Short Put",
                "next_earnings": "2024-06-10",
            }
        ],
        tabulate_fn=tabulate_fn,
        prompt_fn=prompt_fn,
        prompt_yes_no_fn=prompt_yes_no_fn,
        show_proposal_details=show_details,
        refresh_spot_price_fn=mock.Mock(return_value=105.0),
        load_spot_from_metrics_fn=mock.Mock(return_value=None),
        load_latest_close_fn=mock.Mock(return_value=(None, None)),
        spot_from_chain_fn=mock.Mock(return_value=None),
    )

    scan_service.run_market_scan.assert_called_once()
    assert scan_service.run_market_scan.call_args.kwargs["top_n"] == 3
    assert scan_service.run_market_scan.call_args.kwargs["refresh_quotes"] is True
    assert prompt_yes_no_calls == [("Informatie van TWS ophalen y / n: ", False)]
    show_details.assert_called_once_with(session, proposal)
    assert session.symbol == "SPY"
    assert session.strategy == "short_put"
    assert len(tabulate_calls) >= 1


def test_run_market_scan_skips_ib_refresh(
    services: ControlPanelServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = ControlPanelSession()

    config_values = {
        "MARKET_SCAN_TOP_N": 3,
        "STRATEGY_CONFIG": {"dummy": True},
        "INTEREST_RATE": 0.05,
    }

    monkeypatch.setattr(menu_flow.cfg, "get", lambda key, default=None: config_values.get(key, default))
    monkeypatch.setattr(
        menu_flow.ChainPreparationConfig,
        "from_app_config",
        classmethod(lambda cls: SimpleNamespace()),
    )

    scan_service = mock.Mock()
    monkeypatch.setattr(menu_flow, "MarketScanService", mock.Mock(return_value=scan_service))
    scan_service.run_market_scan.return_value = []

    def prompt_fn(message: str) -> str:
        return ""

    def prompt_yes_no_fn(message: str, default: bool) -> bool:
        return False

    def tabulate_fn(rows, **kwargs):
        return "table"

    menu_flow.run_market_scan(
        session,
        services,
        [
            {
                "symbol": "SPY",
                "strategy": "Short Put",
            }
        ],
        tabulate_fn=tabulate_fn,
        prompt_fn=prompt_fn,
        prompt_yes_no_fn=prompt_yes_no_fn,
        show_proposal_details=mock.Mock(),
        refresh_spot_price_fn=mock.Mock(return_value=105.0),
        load_spot_from_metrics_fn=mock.Mock(return_value=None),
        load_latest_close_fn=mock.Mock(return_value=(None, None)),
        spot_from_chain_fn=mock.Mock(return_value=None),
    )

    assert scan_service.run_market_scan.call_args.kwargs["refresh_quotes"] is False
