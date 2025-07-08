import importlib
from pathlib import Path


def test_fetch_earnings_alpha_sleep(monkeypatch, tmp_path):
    mod = importlib.import_module("tomic.cli.fetch_earnings_alpha")
    monkeypatch.setattr(mod, "setup_logging", lambda: None)

    calls = []
    monkeypatch.setattr(mod, "_fetch_symbol", lambda sym, key: calls.append(sym) or ["2025-01-01"])

    sleep_calls = []
    monkeypatch.setattr(mod, "sleep", lambda s: sleep_calls.append(s))

    def fake_load_json(path: Path):
        return {}

    monkeypatch.setattr(mod, "load_json", fake_load_json)

    saved: dict[str, dict] = {}

    def fake_save_json(data, path: Path):
        saved[path.name] = data

    monkeypatch.setattr(mod, "save_json", fake_save_json)

    monkeypatch.setattr(
        mod,
        "cfg_get",
        lambda name, default=None: {
            "ALPHAVANTAGE_API_KEY": "x",
            "ALPHAVANTAGE_SLEEP_BETWEEN": 0.0,
            "DEFAULT_SYMBOLS": ["AAA", "BBB"],
            "EARNINGS_DATES_FILE": tmp_path / "earn.json",
            "EARNINGS_DATA_FILE": tmp_path / "meta.json",
        }.get(name, default),
    )

    mod.main([])

    assert calls == ["AAA", "BBB"]
    assert len(sleep_calls) == 2
    assert "earn.json" in saved
    assert "meta.json" in saved


def test_fetch_earnings_alpha_sorted(monkeypatch, tmp_path):
    mod = importlib.import_module("tomic.cli.fetch_earnings_alpha")
    monkeypatch.setattr(mod, "setup_logging", lambda: None)

    call_order = []

    monkeypatch.setattr(mod, "_fetch_symbol", lambda sym, key: call_order.append(sym) or ["2025-01-01"])

    def fake_load_json(path: Path):
        if Path(path).name == "meta.json":
            return {"AAA": "2025-01-02T00:00:00", "BBB": "2025-01-01T00:00:00"}
        return {}

    monkeypatch.setattr(mod, "load_json", fake_load_json)
    monkeypatch.setattr(mod, "save_json", lambda data, path: None)
    monkeypatch.setattr(mod, "sleep", lambda s: None)
    monkeypatch.setattr(
        mod,
        "cfg_get",
        lambda name, default=None: {
            "ALPHAVANTAGE_API_KEY": "x",
            "ALPHAVANTAGE_SLEEP_BETWEEN": 0.0,
            "DEFAULT_SYMBOLS": ["AAA", "BBB"],
            "EARNINGS_DATES_FILE": tmp_path / "earn.json",
            "EARNINGS_DATA_FILE": tmp_path / "meta.json",
        }.get(name, default),
    )

    mod.main([])

    assert call_order == ["BBB", "AAA"]
