import importlib
import types
import sys


def test_app_controlpanel(monkeypatch):
    tws_stub = types.ModuleType("tomic.proto.tws_daemon")
    monkeypatch.setitem(sys.modules, "tomic.proto.tws_daemon", tws_stub)
    app = importlib.import_module("tomic.cli.app")
    called = []
    monkeypatch.setattr(app.controlpanel, "main", lambda: called.append("cp"))
    app.main(["controlpanel"])
    assert called == ["cp"]


def test_app_csv_quality(monkeypatch):
    tws_stub = types.ModuleType("tomic.proto.tws_daemon")
    monkeypatch.setitem(sys.modules, "tomic.proto.tws_daemon", tws_stub)
    app = importlib.import_module("tomic.cli.app")
    called = []
    monkeypatch.setattr(app.csv_quality_check, "main", lambda argv=None: called.append(argv))
    app.main(["csv-quality-check", "f.csv", "SYM"])
    assert called == [["f.csv", "SYM"]]


def test_app_generate_proposals(monkeypatch):
    tws_stub = types.ModuleType("tomic.proto.tws_daemon")
    monkeypatch.setitem(sys.modules, "tomic.proto.tws_daemon", tws_stub)
    app = importlib.import_module("tomic.cli.app")
    called = []
    monkeypatch.setattr(
        app.generate_proposals,
        "main",
        lambda argv=None: called.append(argv),
    )
    app.main(["generate-proposals", "p.json", "chains"])
    assert called == [["p.json", "chains"]]
