import importlib
from types import SimpleNamespace


def test_compute_volstats_main(monkeypatch):
    mod = importlib.import_module("tomic.cli.compute_volstats")

    # Stub config
    monkeypatch.setattr(mod, "cfg_get", lambda name, default=None: ["ABC"] if name == "DEFAULT_SYMBOLS" else default)

    monkeypatch.setattr(mod, "_get_closes", lambda sym: [1.0] * 100)

    # Stub computations
    monkeypatch.setattr(mod, "fetch_iv30d", lambda sym: 0.25)
    monkeypatch.setattr(
        mod,
        "historical_volatility",
        lambda closes, *, window, trading_days=252: {20: 0.05, 30: 0.1, 90: 0.3, 252: 0.4}[window],
    )

    captured = []
    def fake_update(file, record, keys):
        captured.append(record)
    monkeypatch.setattr(mod, "update_json_file", fake_update)

    mod.main([])

    assert len(captured) == 2
    assert any(r.get("atm_iv") == 0.25 for r in captured)


def test_compute_volstats_no_history(monkeypatch):
    mod = importlib.import_module("tomic.cli.compute_volstats")

    # Stub config
    monkeypatch.setattr(mod, "cfg_get", lambda name, default=None: ["XYZ"] if name == "DEFAULT_SYMBOLS" else default)

    monkeypatch.setattr(mod, "_get_closes", lambda sym: [])

    captured: list[int] = []
    monkeypatch.setattr(mod, "update_json_file", lambda *a, **k: captured.append(1))

    warnings: list[str] = []
    monkeypatch.setattr(mod.logger, "warning", lambda msg, *a, **k: warnings.append(msg % a if a else msg))

    mod.main([])

    assert not captured
    assert any("No price history" in w for w in warnings)

