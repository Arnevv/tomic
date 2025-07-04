import importlib


def test_fetch_single_option_documentation_writes_csv(tmp_path, monkeypatch):
    mod = importlib.import_module("tomic.api.fetch_single_option_documentation")

    rows = [
        {"symbol": "AAA", "expiry": "2025-06-20", "strike": 100, "right": "c"},
        {"symbol": "AAA", "expiry": "2025-06-20", "strike": 100, "right": "Put"},
        {"symbol": "AAA", "expiry": "2025-06-20", "strike": 110, "right": "CALL"},
        {"symbol": "AAA", "expiry": "2025-06-20", "strike": 110, "right": "p"},
    ]
    called = []
    monkeypatch.setattr(
        mod,
        "fetch_contracts",
        lambda symbol, expiry: called.append((symbol, expiry)) or rows,
    )
    monkeypatch.chdir(tmp_path)
    path = mod.run("AAA", "2025-06-20")
    assert path == "MayContracts.csv"
    assert (tmp_path / "MayContracts.csv").exists()
    with open(tmp_path / "MayContracts.csv") as fh:
        lines = [line.strip() for line in fh]
    assert len(lines) == 1 + 4  # header + 2 strikes * 2 rights
    assert called == [("AAA", "2025-06-20")]


def test_dataexporter_menu_invokes_new_scripts(monkeypatch):
    mod = importlib.import_module("tomic.cli.controlpanel")
    called = []
    monkeypatch.setattr(mod, "run_module", lambda name, *a: called.append(name))
    # intercept polygon API call
    polygon_called = []
    monkeypatch.setattr(
        "tomic.providers.polygon_iv.fetch_polygon_option_chain",
        lambda symbol: polygon_called.append(symbol),
    )
    inputs = iter(["1", "AAA", "2", "BBB", "5"])
    monkeypatch.setattr("builtins.input", lambda *a: next(inputs))
    mod.run_dataexporter()
    assert "tomic.cli.option_lookup_bulk" in called
    assert polygon_called
