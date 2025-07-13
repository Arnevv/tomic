import importlib
import json
import builtins
import sys
import types


def test_get_iv_rank_main(monkeypatch):
    mod = importlib.import_module("tomic.analysis.get_iv_rank")
    monkeypatch.setattr(
        mod,
        "fetch_iv_metrics",
        lambda symbol="SPY": {
            "iv_rank": 50.0,
            "implied_volatility": 0.2,
            "iv_percentile": 80.0,
        },
    )
    messages = []
    monkeypatch.setattr(
        mod.logger, "info", lambda msg, *a, **k: messages.append(msg.format(*a))
    )
    monkeypatch.setattr(
        mod.logger, "success", lambda msg, *a, **k: messages.append(msg)
    )
    mod.main(["ABC"])
    assert any("Metrics fetched" in m for m in messages)


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
    monkeypatch.setattr(mod, "run_module", lambda m: None)
    monkeypatch.setattr(mod, "run_portfolio_menu", lambda: None)
    monkeypatch.setattr(mod, "run_trade_management", lambda: None)
    monkeypatch.setattr(mod, "run_dataexporter", lambda: None)
    monkeypatch.setattr(mod, "run_risk_tools", lambda: None)
    monkeypatch.setattr(mod, "run_settings_menu", lambda: None)
    monkeypatch.setattr(builtins, "input", lambda prompt="": "8")
    mod.main()


def test_entry_checker_main(tmp_path, monkeypatch):
    mod = importlib.import_module("tomic.cli.entry_checker")
    pos = tmp_path / "p.json"
    pos.write_text("[]")
    monkeypatch.setattr(mod, "cfg_get", lambda name, default=None: str(pos))
    dashboard_stub = types.ModuleType("tomic.analysis.strategy")
    dashboard_stub.group_strategies = lambda positions: [{"symbol": "AAA", "type": "X"}]
    monkeypatch.setitem(sys.modules, "tomic.analysis.strategy", dashboard_stub)
    monkeypatch.setattr(mod, "check_entry_conditions", lambda strat: ["warn"])
    lines = []
    monkeypatch.setattr(
        builtins, "print", lambda *a, **k: lines.append(" ".join(str(x) for x in a))
    )
    mod.main([str(pos)])
    assert any("warn" in line for line in lines)




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


def test_portfolio_scenario_main(monkeypatch):
    mod = importlib.import_module("tomic.cli.portfolio_scenario")
    monkeypatch.setattr(mod, "load_positions", lambda p: [])
    monkeypatch.setattr(mod, "group_strategies", lambda positions: [])
    monkeypatch.setattr(
        mod,
        "simulate_portfolio_response",
        lambda s, ss, iv: {
            "totals": {"delta": 0, "vega": 0, "theta": 0},
            "pnl_change": 0,
            "rom_before": 0,
            "rom_after": 0,
        },
    )
    inputs = iter(["2", "5", "n"])
    monkeypatch.setattr(builtins, "input", lambda *args: next(inputs))
    mod.main(["pos.json"])


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


def test_synthetics_detector_main(tmp_path, monkeypatch):
    mod = importlib.import_module("tomic.cli.synthetics_detector")
    path = tmp_path / "p.json"
    path.write_text("[]")
    monkeypatch.setattr(mod, "cfg_get", lambda name, default=None: str(path))
    dashboard_stub = types.ModuleType("tomic.analysis.strategy")
    dashboard_stub.group_strategies = lambda positions: [
        {"symbol": "AAA", "type": "Test", "legs": []}
    ]
    monkeypatch.setitem(sys.modules, "tomic.analysis.strategy", dashboard_stub)
    monkeypatch.setattr(
        mod, "analyze_synthetics_and_edge", lambda s: {"synthetic": "stock"}
    )
    output = []
    monkeypatch.setattr(
        builtins, "print", lambda *a, **k: output.append(" ".join(str(x) for x in a))
    )
    mod.main([str(path)])
    assert output


def test_risk_tools_generate_proposals(monkeypatch):
    rpc_stub = types.ModuleType("tomic.proto.rpc")
    rpc_stub.submit_task = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "tomic.proto.rpc", rpc_stub)
    mod = importlib.import_module("tomic.cli.controlpanel")
    called = []
    monkeypatch.setattr(mod, "run_module", lambda name, *a: called.append(name))
    inputs = iter(["4", "7"])
    monkeypatch.setattr(builtins, "input", lambda *a: next(inputs))
    mod.run_risk_tools()
    assert called == ["tomic.cli.generate_proposals"]


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
    export_stub = types.ModuleType("tomic.api.market_export")
    export_stub.ExportResult = type("ExportResult", (), {})
    export_stub.export_market_data = lambda sym, out=None, **k: sym
    monkeypatch.setitem(sys.modules, "tomic.api.market_export", export_stub)
    rpc_stub = types.ModuleType("tomic.proto.rpc")
    rpc_stub.submit_task = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "tomic.proto.rpc", rpc_stub)
    mod = importlib.reload(importlib.import_module("tomic.api.getonemarket"))
    monkeypatch.setattr(mod, "setup_logging", lambda: None)
    called = []

    def stub_connect_ib(*a, **k):
        called.append(True)
        return types.SimpleNamespace(disconnect=lambda: None, next_valid_id=1)

    monkeypatch.setattr(mod, "connect_ib", stub_connect_ib)
    assert mod.run("ABC") is True
    assert not called


def test_getallmarkets_run(monkeypatch):
    export_stub = types.ModuleType("tomic.api.market_export")
    export_stub.ExportResult = type("ExportResult", (), {})
    export_stub.export_market_data = lambda sym, out=None, **k: sym
    monkeypatch.setitem(sys.modules, "tomic.api.market_export", export_stub)
    mod = importlib.reload(importlib.import_module("tomic.api.getallmarkets"))
    monkeypatch.setattr(mod, "connect_ib", lambda *a, **k: types.SimpleNamespace(disconnect=lambda: None))
    assert mod.run("XYZ") == "XYZ"


def test_option_lookup_main_invalid_args(monkeypatch):
    mod = importlib.import_module("tomic.cli.option_lookup")
    monkeypatch.setattr(mod, "setup_logging", lambda: None)
    output = []
    monkeypatch.setattr(
        builtins, "print", lambda *a, **k: output.append(" ".join(str(x) for x in a))
    )
    mod.main(["SPY", "A", "B", "C"])
    assert any("Usage" in line for line in output)
