import importlib


def test_fetch_single_option_documentation_writes_csv(tmp_path, monkeypatch):
    mod = importlib.import_module("tomic.api.fetch_single_option_documentation")

    class Resp:
        def __init__(self, data):
            self.data = data
        def json(self):
            return self.data
        def raise_for_status(self):
            pass

    calls = []
    def fake_get(url, params=None):
        calls.append((url, dict(params or {})))
        if url.endswith("/search"):
            return Resp([{"conid": "1"}])
        if url.endswith("/strikes"):
            return Resp({"strikes": [100, 110]})
        if url.endswith("/info"):
            strike = params.get("strike")
            right = params.get("right")
            return Resp({"conid": f"{strike}{right}"})
        raise AssertionError("unexpected url")

    monkeypatch.setattr(mod.requests, "get", fake_get, raising=False)
    monkeypatch.chdir(tmp_path)
    path = mod.run("AAA", "2025-06-20")
    assert path == "MayContracts.csv"
    assert (tmp_path / "MayContracts.csv").exists()
    with open(tmp_path / "MayContracts.csv") as fh:
        lines = [line.strip() for line in fh]
    assert len(lines) == 1 + 4  # header + 2 strikes * 2 rights
    assert calls[0][0].endswith("/search")
    assert calls[1][0].endswith("/strikes")
    assert calls[2][0].endswith("/info")


def test_dataexporter_menu_invokes_new_script(monkeypatch):
    mod = importlib.import_module("tomic.cli.controlpanel")
    called = []
    monkeypatch.setattr(mod, "run_module", lambda name, *a: called.append(name))
    inputs = iter(["5", "6", "7"])
    monkeypatch.setattr("builtins.input", lambda *a: next(inputs))
    mod.run_dataexporter()
    assert "tomic.api.fetch_single_option_documentation" in called
