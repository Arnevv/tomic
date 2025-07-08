import importlib

def test_fetch_earnings_alpha_sleep(monkeypatch, tmp_path):
    mod = importlib.import_module("tomic.cli.fetch_earnings_alpha")
    monkeypatch.setattr(mod, "setup_logging", lambda: None)
    monkeypatch.setattr(mod, "_fetch_symbol", lambda sym, key: ["2025-01-01"])
    monkeypatch.setattr(mod, "load_json", lambda path: {})
    stored = {}
    monkeypatch.setattr(mod, "save_json", lambda data, path: stored.update(data))
    sleeps = []
    monkeypatch.setattr(mod, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(
        mod,
        "cfg_get",
        lambda name, default=None: {
            "ALPHAVANTAGE_API_KEY": "x",
            "ALPHAVANTAGE_SLEEP_BETWEEN": 0.0,
            "DEFAULT_SYMBOLS": ["AAA", "BBB"],
            "EARNINGS_DATES_FILE": str(tmp_path / "earn.json"),
        }.get(name, default),
    )

    mod.main([])
    assert list(stored.keys()) == ["AAA", "BBB"]
    assert len(sleeps) == 2
