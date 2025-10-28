from pathlib import Path

from tomic.cli import exit_flow as cli_mod
from tomic.services.exit_flow import ExitAttemptResult, ExitFlowConfig, ExitFlowResult
from tomic.services.trade_management_service import (
    StrategyExitIntent,
    StrategyManagementSummary,
)


def _make_config(tmp_path: Path) -> ExitFlowConfig:
    return ExitFlowConfig(
        host="127.0.0.1",
        port=4002,
        client_id=1,
        account=None,
        order_type="LMT",
        tif="DAY",
        fetch_only=False,
        force_exit_enabled=False,
        market_order_on_force=False,
        log_directory=tmp_path,
    )


def test_exit_flow_cli_runs(monkeypatch, tmp_path):
    intent = StrategyExitIntent(strategy={"symbol": "XYZ", "expiry": "20240119"}, legs=[], exit_rules=None)

    monkeypatch.setattr(cli_mod, "setup_logging", lambda: None)
    monkeypatch.setattr(
        cli_mod,
        "build_management_summary",
        lambda positions_file=None, journal_file=None: [
            StrategyManagementSummary(
                symbol="XYZ",
                expiry="20240119",
                strategy="iron_condor",
                spot=None,
                unrealized_pnl=None,
                days_to_expiry=None,
                exit_trigger="🚨",
                status="⚠️ Beheer nodig",
            )
        ],
    )
    monkeypatch.setattr(
        cli_mod,
        "build_exit_intents",
        lambda positions_file=None, journal_file=None, **kwargs: [intent],
    )

    captured = []

    def fake_execute(intent_arg, config):
        captured.append(intent_arg)
        return ExitFlowResult(
            status="success",
            reason="primary",
            limit_prices=(1.23,),
            order_ids=(10,),
            attempts=(ExitAttemptResult(stage="primary", status="success", limit_price=1.23, order_ids=(10,)),),
            forced=False,
        )

    monkeypatch.setattr(cli_mod, "execute_exit_flow", fake_execute)
    monkeypatch.setattr(cli_mod, "store_exit_flow_result", lambda intent_arg, result, directory: tmp_path / "exit.json")
    monkeypatch.setattr(cli_mod.ExitFlowConfig, "from_app_config", classmethod(lambda cls: _make_config(tmp_path)))

    code = cli_mod.main([])
    assert code == 0
    assert captured == [intent]


def test_exit_flow_cli_symbol_filter(monkeypatch, tmp_path):
    intents = [
        StrategyExitIntent(strategy={"symbol": "AAA", "expiry": "20240119"}, legs=[], exit_rules=None),
        StrategyExitIntent(strategy={"symbol": "BBB", "expiry": "20240119"}, legs=[], exit_rules=None),
    ]

    monkeypatch.setattr(cli_mod, "setup_logging", lambda: None)
    monkeypatch.setattr(
        cli_mod,
        "build_management_summary",
        lambda positions_file=None, journal_file=None: [
            StrategyManagementSummary(
                symbol="AAA",
                expiry="20240119",
                strategy=None,
                spot=None,
                unrealized_pnl=None,
                days_to_expiry=None,
                exit_trigger="",
                status="✅ Houden",
            ),
            StrategyManagementSummary(
                symbol="BBB",
                expiry="20240119",
                strategy=None,
                spot=None,
                unrealized_pnl=None,
                days_to_expiry=None,
                exit_trigger="🚨",
                status="⚠️ Beheer nodig",
            ),
        ],
    )
    monkeypatch.setattr(
        cli_mod,
        "build_exit_intents",
        lambda positions_file=None, journal_file=None, **kwargs: intents,
    )

    executed: list[str] = []

    def fake_execute(intent_arg, config):
        executed.append(intent_arg.strategy.get("symbol"))
        return ExitFlowResult(
            status="failed",
            reason="primary",
            limit_prices=tuple(),
            order_ids=tuple(),
            attempts=tuple(),
            forced=False,
        )

    monkeypatch.setattr(cli_mod, "execute_exit_flow", fake_execute)
    monkeypatch.setattr(cli_mod, "store_exit_flow_result", lambda intent_arg, result, directory: tmp_path / "exit.json")
    monkeypatch.setattr(cli_mod.ExitFlowConfig, "from_app_config", classmethod(lambda cls: _make_config(tmp_path)))

    code = cli_mod.main(["--symbol", "BBB"])
    assert code == 1  # failure due to result.status == failed
    assert executed == ["BBB"]


def test_exit_flow_cli_skips_without_alert(monkeypatch, tmp_path):
    intent = StrategyExitIntent(strategy={"symbol": "QQQ", "expiry": "20250117"}, legs=[], exit_rules=None)

    monkeypatch.setattr(cli_mod, "setup_logging", lambda: None)
    monkeypatch.setattr(
        cli_mod,
        "build_management_summary",
        lambda positions_file=None, journal_file=None: [
            StrategyManagementSummary(
                symbol="QQQ",
                expiry="20250117",
                strategy="iron_condor",
                spot=None,
                unrealized_pnl=None,
                days_to_expiry=None,
                exit_trigger="geen trigger",
                status="✅ Houden",
            )
        ],
    )
    monkeypatch.setattr(
        cli_mod,
        "build_exit_intents",
        lambda positions_file=None, journal_file=None, **kwargs: [intent],
    )

    executed: list[StrategyExitIntent] = []

    def fake_execute(intent_arg, config):
        executed.append(intent_arg)
        return ExitFlowResult(
            status="success",
            reason="primary",
            limit_prices=(1.0,),
            order_ids=(1,),
            attempts=(ExitAttemptResult(stage="primary", status="success", limit_price=1.0, order_ids=(1,)),),
            forced=False,
        )

    monkeypatch.setattr(cli_mod, "execute_exit_flow", fake_execute)
    monkeypatch.setattr(cli_mod, "store_exit_flow_result", lambda intent_arg, result, directory: tmp_path / "exit.json")
    monkeypatch.setattr(cli_mod.ExitFlowConfig, "from_app_config", classmethod(lambda cls: _make_config(tmp_path)))

    code = cli_mod.main([])
    assert code == 0
    assert executed == []
