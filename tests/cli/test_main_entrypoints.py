import importlib
import json
import builtins
import sys
import types

import pytest


def test_get_iv_rank_main(monkeypatch):
    mod = importlib.import_module("tomic.analysis.get_iv_rank")
    monkeypatch.setattr(
        mod,
        "fetch_iv_metrics",
        lambda symbol="SPY": {
            "iv_rank": 0.50,
            "implied_volatility": 0.2,
            "iv_percentile": 0.80,
        },
    )
    messages = []
    def _capture(msg, *a, **k):
        try:
            formatted = msg.format(*a, **k)
        except Exception:
            formatted = msg
        messages.append(formatted)

    monkeypatch.setattr(mod.logger, "info", _capture)
    monkeypatch.setattr(mod.logger, "success", _capture)
    mod.main(["ABC"])
    assert any("IV metrics for ABC" in m for m in messages)


def test_performance_analyzer_main(tmp_path, monkeypatch):
    mod = importlib.import_module("tomic.analysis.performance_analyzer")
    monkeypatch.setattr(mod, "setup_logging", lambda: None)
    monkeypatch.setattr(
        mod,
        "load_journal",
        lambda path="": [
            {"DatumUit": "2024-01-01", "Type": "Test", "EntryPrice": 3, "ExitPrice": 2}
        ],
    )
    monkeypatch.setattr(
        mod,
        "analyze",
        lambda trades: {
            "Test": {
                "trades": 1,
                "winrate": 1.0,
                "avg_win": 100.0,
                "avg_loss": 0.0,
                "expectancy": 100.0,
                "max_drawdown": -10.0,
            }
        },
    )
    out_path = tmp_path / "stats.json"
    monkeypatch.setattr(mod.logger, "error", lambda *a, **k: None)
    monkeypatch.setattr(mod.logger, "info", lambda *a, **k: None)
    monkeypatch.setattr(mod.logger, "success", lambda *a, **k: None)
    mod.main([str(out_path), "--json-output", str(out_path)])
    data = json.loads(out_path.read_text())
    assert data["stats"]["Test"]["trades"] == 1




def test_close_trade_main(monkeypatch):
    mod = importlib.import_module("tomic.cli.close_trade")
    trade = {"TradeID": "1", "Symbool": "ABC", "Type": "T", "Status": "Open"}
    monkeypatch.setattr(mod, "load_journal", lambda: [trade])
    monkeypatch.setattr(mod, "sluit_trade_af", lambda t: None)
    monkeypatch.setattr(mod.logger, "error", lambda *a, **k: None)
    monkeypatch.setattr(mod.logger, "success", lambda *a, **k: None)
    monkeypatch.setattr(builtins, "input", lambda prompt="": "1")
    mod.main()


def test_event_watcher_main(tmp_path, monkeypatch):
    mod = importlib.import_module("tomic.cli.event_watcher")
    positions_path = tmp_path / "pos.json"
    positions_path.write_text("[]")
    monkeypatch.setattr(mod, "setup_logging", lambda: None)
    monkeypatch.setattr(mod, "cfg_get", lambda name, default=None: str(positions_path))
    dashboard_stub = types.ModuleType("tomic.analysis.strategy")
    dashboard_stub.group_strategies = lambda pos: [{"symbol": "AAA"}]
    monkeypatch.setitem(sys.modules, "tomic.analysis.strategy", dashboard_stub)
    monkeypatch.setattr(
        mod, "apply_event_alerts", lambda strategies, event_json_path="": None
    )
    monkeypatch.setattr(mod.logger, "info", lambda *a, **k: None)
    monkeypatch.setattr(mod.logger, "success", lambda *a, **k: None)
    mod.main([str(positions_path)])


def test_controlpanel_main(monkeypatch):
    rpc_stub = types.ModuleType("tomic.proto.rpc")
    rpc_stub.submit_task = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "tomic.proto.rpc", rpc_stub)
    mod = importlib.import_module("tomic.cli.controlpanel")
    section_titles = [section.title for section in mod.ROOT_SECTIONS]
    assert section_titles == [
        "Analyse & Strategie",
        "Data & Marktdata",
        "Trades & Journal",
        "Configuratie",
    ]
    assert not hasattr(mod, "run_risk_tools")
    monkeypatch.setattr(mod, "run_module", lambda m: None)
    monkeypatch.setattr(mod, "run_portfolio_menu", lambda: None)
    monkeypatch.setattr(mod, "run_trade_management", lambda: None)
    monkeypatch.setattr(mod, "run_dataexporter", lambda: None)
    monkeypatch.setattr(mod, "run_settings_menu", lambda: None)
    monkeypatch.setattr(builtins, "input", lambda prompt="": "8")
    mod.main()




def test_csv_quality_check_main(tmp_path, monkeypatch):
    mod = importlib.import_module("tomic.cli.csv_quality_check")
    csv_path = tmp_path / "file.csv"
    csv_path.write_text("x")
    monkeypatch.setattr(mod, "setup_logging", lambda: None)
    monkeypatch.setattr(mod.os.path, "isfile", lambda p: True)
    monkeypatch.setattr(
        mod,
        "analyze_csv",
        lambda p: {
            "total": 1,
            "complete": 1,
            "valid": 1,
            "expiries": [],
            "bad_delta": 0,
            "bad_price_fields": 0,
            "duplicates": 0,
            "empty_counts": {
                "bid": 0,
                "ask": 0,
                "iv": 0,
                "delta": 0,
                "gamma": 0,
                "vega": 0,
                "theta": 0,
            },
            "minus_one_quotes": 0,
        },
    )
    monkeypatch.setattr(mod.logger, "warning", lambda *a, **k: None)
    monkeypatch.setattr(mod.logger, "success", lambda *a, **k: None)
    mod.main([str(csv_path), "SYM"])


@pytest.mark.parametrize(
    "removed_module",
    [
        "tomic.cli.entry_checker",
        "tomic.cli.portfolio_scenario",
        "tomic.cli.synthetics_detector",
    ],
)
def test_removed_cli_modules_raise_import_error(removed_module):
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(removed_module)


def test_link_positions_main(monkeypatch):
    mod = importlib.import_module("tomic.cli.link_positions")
    monkeypatch.setattr(mod, "setup_logging", lambda: None)
    monkeypatch.setattr(mod, "load_journal", lambda path=mod.JOURNAL_FILE: [])
    monkeypatch.setattr(mod, "load_json", lambda path: [])
    monkeypatch.setattr(mod, "list_open_trades", lambda j: [])
    monkeypatch.setattr(mod, "choose_trade", lambda trades: None)
    monkeypatch.setattr(mod, "choose_leg", lambda trade: None)
    monkeypatch.setattr(mod, "save_journal", lambda j: None)
    monkeypatch.setattr(mod.logger, "success", lambda *a, **k: None)
    mod.main()




def test_trading_plan_main(capsys):
    from tomic.cli import trading_plan

    trading_plan.main()
    out = capsys.readouterr().out
    assert "TOMIC Trading Plan" in out


def test_strategy_dashboard_main(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "tomic.api.getaccountinfo", types.ModuleType("getaccountinfo"))
    mod = importlib.import_module("tomic.cli.strategy_dashboard")
    pos = tmp_path / "p.json"
    pos.write_text("[]")
    acc = tmp_path / "a.json"
    acc.write_text("{}")
    monkeypatch.setattr(mod, "load_positions", lambda p: [])
    monkeypatch.setattr(mod, "load_account_info", lambda p: {})
    monkeypatch.setattr(mod, "load_journal", lambda p: [])
    monkeypatch.setattr(mod, "extract_exit_rules", lambda p: {})
    monkeypatch.setattr(mod, "compute_portfolio_greeks", lambda p: {})
    monkeypatch.setattr(mod, "print_account_summary", lambda *a, **k: None)
    monkeypatch.setattr(mod, "print_account_overview", lambda *a, **k: None)
    monkeypatch.setattr(mod, "group_strategies", lambda p, journal=None: [])
    monkeypatch.setattr(mod, "compute_term_structure", lambda s: None)
    monkeypatch.setattr(mod, "print_strategy_full", lambda *a, **k: None)
    res = mod.main([str(pos), str(acc)])
    assert res == 0


def test_journal_inspector_main(monkeypatch):
    mod = importlib.import_module("tomic.journal.journal_inspector")
    monkeypatch.setattr(mod, "load_journal", lambda: [])
    monkeypatch.setattr(mod, "toon_overzicht", lambda j: None)
    monkeypatch.setattr(builtins, "input", lambda *a: "")
    mod.main()


def test_getonemarket_run(monkeypatch):
    mod = importlib.reload(importlib.import_module("tomic.api.getonemarket"))
    monkeypatch.setattr(mod, "setup_logging", lambda: None)

    with pytest.raises(RuntimeError):
        mod.run("ABC")


def test_getallmarkets_run(monkeypatch):
    mod = importlib.reload(importlib.import_module("tomic.api.getallmarkets"))

    with pytest.raises(RuntimeError):
        mod.run("XYZ")


def test_option_lookup_main_invalid_args(monkeypatch):
    mod = importlib.import_module("tomic.cli.option_lookup")
    monkeypatch.setattr(mod, "setup_logging", lambda: None)
    output = []
    monkeypatch.setattr(
        builtins, "print", lambda *a, **k: output.append(" ".join(str(x) for x in a))
    )
    mod.main(["SPY", "A", "B", "C"])
    assert any("Usage" in line for line in output)
