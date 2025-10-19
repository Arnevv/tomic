import importlib


def _import_app(monkeypatch):
    log_mod = importlib.import_module("tomic.logutils")
    if not hasattr(log_mod, "summarize_evaluations"):
        monkeypatch.setattr(log_mod, "summarize_evaluations", lambda captured: {}, raising=False)
    pipeline_mod = importlib.import_module("tomic.services.pipeline_refresh")
    if not hasattr(pipeline_mod, "RefreshProposal"):
        monkeypatch.setattr(pipeline_mod, "RefreshProposal", pipeline_mod.Proposal, raising=False)
    return importlib.import_module("tomic.cli.app")


def test_cli_dispatch_controlpanel(monkeypatch):
    mod = _import_app(monkeypatch)
    called = []
    monkeypatch.setattr(mod.controlpanel, "main", lambda: called.append("controlpanel"))
    mod.main(["controlpanel"])
    assert called == ["controlpanel"]


def test_cli_dispatch_csv_quality(monkeypatch):
    mod = _import_app(monkeypatch)
    received = []
    monkeypatch.setattr(mod.csv_quality_check, "main", lambda args: received.append(args))
    mod.main(["csv-quality-check", "path.csv", "SYM"])
    assert received == [["path.csv", "SYM"]]


def test_cli_dispatch_option_lookup(monkeypatch):
    mod = _import_app(monkeypatch)
    received = []
    monkeypatch.setattr(mod.option_lookup, "main", lambda args: received.append(args))
    mod.main(["option-lookup", "SPY", "2024-01-19", "400", "call"])
    assert received == [["SPY", "2024-01-19", "400", "call"]]


def test_cli_dispatch_portfolio_scenario(monkeypatch):
    mod = _import_app(monkeypatch)
    received = []
    monkeypatch.setattr(mod.portfolio_scenario, "main", lambda args: received.append(args))
    mod.main(["portfolio-scenario", "positions.json"])
    assert received == [["positions.json"]]


def test_cli_dispatch_generate_proposals(monkeypatch):
    mod = _import_app(monkeypatch)
    received = []
    monkeypatch.setattr(mod.generate_proposals, "main", lambda args: received.append(args))
    mod.main(["generate-proposals", "positions.json", "exports"])
    assert received == [["positions.json", "exports"]]


def test_cli_dispatch_rules_show(monkeypatch):
    mod = _import_app(monkeypatch)
    received = []
    monkeypatch.setattr(mod.rules, "main", lambda args: received.append(args))
    mod.main(["rules", "show", "criteria.yaml"])
    assert received == [["show", "criteria.yaml"]]


def test_cli_dispatch_rules_validate(monkeypatch):
    mod = _import_app(monkeypatch)
    received = []
    monkeypatch.setattr(mod.rules, "main", lambda args: received.append(args))
    mod.main(["rules", "validate", "criteria.yaml", "--reload"])
    assert received == [["validate", "criteria.yaml", "--reload"]]


def test_cli_dispatch_rules_reload(monkeypatch):
    mod = _import_app(monkeypatch)
    received = []
    monkeypatch.setattr(mod.rules, "main", lambda args: received.append(args))
    mod.main(["rules", "reload", "criteria.yaml"])
    assert received == [["reload", "criteria.yaml"]]
