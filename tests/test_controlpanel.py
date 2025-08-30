import builtins
import importlib


def test_portfolio_menu_option_calls_trade_management(monkeypatch):
    mod = importlib.import_module("tomic.cli.controlpanel")
    called = {}
    monkeypatch.setattr(mod, "run_module", lambda name, *a: called.setdefault("name", name))
    inputs = iter(["4", "9"])
    monkeypatch.setattr(builtins, "input", lambda *a, **k: next(inputs))
    mod.run_portfolio_menu()
    assert called.get("name") == "tomic.cli.trade_management"
