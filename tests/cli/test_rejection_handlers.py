from types import SimpleNamespace

from tomic.cli.controlpanel_session import ControlPanelSession
from tomic.cli.rejections import handlers
from tomic.services.strategy_pipeline import RejectionSummary, StrategyProposal
from tomic.strategy.reasons import ReasonCategory


class DummyConfig:
    def __init__(self, values: dict[str, object] | None = None) -> None:
        self._values = values or {}

    def get(self, key: str, default: object | None = None) -> object | None:
        return self._values.get(key, default)


def test_show_rejection_detail_triggers_callback(monkeypatch, capsys):
    session = ControlPanelSession()
    proposal = StrategyProposal(strategy="Test", legs=[{"symbol": "XYZ"}])
    entry = {
        "strategy": "Test",
        "status": "reject",
        "description": "Some anchor",
        "reason": ReasonCategory.WIDE_SPREAD,
        "metrics": {"edge": 0.12},
        "meta": {"symbol": "XYZ"},
        "legs": [
            {
                "expiry": "2024-01-01",
                "type": "CALL",
                "strike": 100,
                "position": 1,
                "bid": 1.0,
                "ask": 1.2,
                "mid": 1.1,
            }
        ],
    }

    monkeypatch.setattr(handlers, "build_proposal_from_entry", lambda _: proposal)

    prompts = iter(["1", "0"])
    called: dict[str, bool] = {}

    def fake_details(sess: ControlPanelSession, prop: StrategyProposal) -> None:
        called["called"] = sess is session and prop is proposal

    handlers.show_rejection_detail(
        session,
        entry,
        tabulate_fn=lambda rows, headers, tablefmt: "table",
        prompt_fn=lambda _: next(prompts),
        show_proposal_details=fake_details,
    )

    output = capsys.readouterr().out
    assert "Strategie: Test" in output
    assert called.get("called") is True


def test_build_rejection_summary_refreshes_all(monkeypatch, capsys):
    session = ControlPanelSession()
    session.combo_evaluations = [
        {
            "status": "reject",
            "reason": "Too wide",
            "strategy": "Test",
            "legs": [],
        }
    ]
    summary = RejectionSummary(
        by_filter={"width": 2},
        by_reason={"Too wide": 2},
        by_strategy={"Test": []},
    )

    refreshed: dict[str, list] = {}

    def fake_refresh(sess, services, entries, **kwargs):
        refreshed.setdefault("calls", []).append((sess, tuple(entries)))

    monkeypatch.setattr(handlers, "refresh_rejections", fake_refresh)

    prompts = iter(["a", "0"])

    handlers.build_rejection_summary(
        session,
        summary,
        services=SimpleNamespace(),
        config=DummyConfig(),
        show_reasons=True,
        tabulate_fn=lambda rows, headers, tablefmt: "table",
        prompt_fn=lambda _: next(prompts),
        prompt_yes_no_fn=lambda *_: True,
        show_proposal_details=lambda *_: None,
    )

    assert refreshed["calls"][0][0] is session
    assert len(refreshed["calls"][0][1]) == 1
    cap = capsys.readouterr().out
    assert "Afwijzingen per filter" in cap


def test_refresh_rejections_updates_entries(monkeypatch):
    session = ControlPanelSession(run_id="trace")
    session.symbol = "XYZ"
    session.spot_price = 123.0

    entry: dict[str, object] = {
        "status": "reject",
        "strategy": "Test",
        "meta": {"symbol": "XYZ"},
    }
    proposal = StrategyProposal(strategy="Test", legs=[{"symbol": "XYZ"}])

    monkeypatch.setattr(handlers, "build_proposal_from_entry", lambda _: proposal)
    monkeypatch.setattr(handlers, "load_criteria", lambda: {"dummy": True})

    accepted_item = SimpleNamespace(
        source=handlers.RefreshSource(index=0, entry=entry, symbol="XYZ"),
        proposal=proposal,
        reasons=[],
        missing_quotes=[],
        error=None,
    )
    result = SimpleNamespace(
        stats=SimpleNamespace(accepted=1, rejected=0),
        accepted=[accepted_item],
        rejections=[],
    )

    captured: dict[str, object] = {}

    def fake_refresh_pipeline(context, params):
        captured["timeout"] = params.timeout
        captured["max_attempts"] = params.max_attempts
        captured["retry_delay"] = params.retry_delay
        captured["parallel"] = params.parallel
        return result

    monkeypatch.setattr(handlers, "refresh_pipeline", fake_refresh_pipeline)
    monkeypatch.setattr(
        handlers,
        "build_proposal_viewmodel",
        lambda _: SimpleNamespace(warnings=[], accepted=True, reasons=[], has_missing_edge=False),
    )
    monkeypatch.setattr(handlers, "sort_records", lambda records, spec: list(records))
    monkeypatch.setattr(handlers, "proposals_table", lambda records, spec: (["col"], [["row"]]))

    prompts = iter(["0"])

    config = DummyConfig(
        {
            "MARKET_DATA_TIMEOUT": 7,
            "PIPELINE_REFRESH_ATTEMPTS": 3,
            "PIPELINE_REFRESH_RETRY_DELAY": 2,
            "PIPELINE_REFRESH_PARALLEL": True,
        }
    )

    handlers.refresh_rejections(
        session,
        services=SimpleNamespace(),
        entries=[entry],
        config=config,
        show_proposal_details=lambda *_: None,
        tabulate_fn=lambda rows, headers, tablefmt: "table",
        prompt_fn=lambda _: next(prompts),
    )

    assert entry["refreshed_accepted"] is True
    assert entry["refreshed_proposal"] is proposal
    assert entry["refreshed_symbol"] == "XYZ"
    assert captured["timeout"] == 7
    assert captured["max_attempts"] == 3
    assert captured["retry_delay"] == 2.0
    assert captured["parallel"] is True
