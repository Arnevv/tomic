import importlib
import json
from datetime import datetime


def test_fetch_iv_polygon_main(monkeypatch, tmp_path):
    mod = importlib.import_module("tomic.cli.fetch_iv_polygon")

    monkeypatch.setattr(mod, "setup_logging", lambda: None)
    monkeypatch.setattr(
        mod,
        "cfg_get",
        lambda name, default=None: (
            ["ABC"] if name == "DEFAULT_SYMBOLS" else str(tmp_path) if name == "IV_DAILY_SUMMARY_DIR" else default
        ),
    )
    monkeypatch.setattr(
        mod,
        "fetch_polygon_iv30d",
        lambda sym: {"atm_iv": 0.21, "skew": 0.0, "term_m1_m2": None, "term_m1_m3": None},
    )

    captured = []
    monkeypatch.setattr(mod, "update_json_file", lambda f, rec, keys: captured.append((f, rec)))

    class FakeDT(datetime):
        @classmethod
        def now(cls):
            return datetime(2024, 1, 1)

    monkeypatch.setattr(mod, "datetime", FakeDT)
    monkeypatch.setattr(mod, "sleep", lambda s: None)

    mod.main([])

    assert captured
    file, rec = captured[0]
    assert "ABC.json" in str(file)
    assert rec["atm_iv"] == 0.21
    assert rec["iv_rank"] is None
    assert rec["iv_percentile"] is None


def test_fetch_iv_polygon_skip_existing(monkeypatch, tmp_path):
    mod = importlib.import_module("tomic.cli.fetch_iv_polygon")

    monkeypatch.setattr(mod, "setup_logging", lambda: None)
    monkeypatch.setattr(
        mod,
        "cfg_get",
        lambda name, default=None: (
            ["ABC"]
            if name == "DEFAULT_SYMBOLS"
            else str(tmp_path)
            if name == "IV_DAILY_SUMMARY_DIR"
            else default
        ),
    )
    monkeypatch.setattr(
        mod,
        "fetch_polygon_iv30d",
        lambda sym: {"atm_iv": 0.22, "skew": 0.0, "term_m1_m2": None, "term_m1_m3": None},
    )

    (tmp_path / "ABC.json").write_text(
        json.dumps([{"date": "2024-01-01", "atm_iv": 0.1}])
    )

    called = []
    monkeypatch.setattr(mod, "update_json_file", lambda *a, **k: called.append(1))

    class FakeDT(datetime):
        @classmethod
        def now(cls):
            return datetime(2024, 1, 1)

    messages = []
    monkeypatch.setattr(mod.logger, "info", lambda msg, *a, **k: messages.append(msg.format(*a)))
    monkeypatch.setattr(mod, "datetime", FakeDT)
    monkeypatch.setattr(mod, "sleep", lambda s: None)

    mod.main([])

    assert not called
    assert any("al aanwezig" in m for m in messages)


def test_fetch_iv_polygon_refetch_when_null(monkeypatch, tmp_path):
    mod = importlib.import_module("tomic.cli.fetch_iv_polygon")

    monkeypatch.setattr(mod, "setup_logging", lambda: None)
    monkeypatch.setattr(
        mod,
        "cfg_get",
        lambda name, default=None: (
            ["ABC"]
            if name == "DEFAULT_SYMBOLS"
            else str(tmp_path)
            if name == "IV_DAILY_SUMMARY_DIR"
            else default
        ),
    )
    monkeypatch.setattr(
        mod,
        "fetch_polygon_iv30d",
        lambda sym: {"atm_iv": 0.23, "skew": 0.0, "term_m1_m2": None, "term_m1_m3": None},
    )

    (tmp_path / "ABC.json").write_text(
        json.dumps([{"date": "2024-01-01", "atm_iv": None}])
    )

    captured = []
    monkeypatch.setattr(mod, "update_json_file", lambda f, rec, keys: captured.append(rec))

    class FakeDT(datetime):
        @classmethod
        def now(cls):
            return datetime(2024, 1, 1)

    monkeypatch.setattr(mod, "datetime", FakeDT)
    monkeypatch.setattr(mod, "sleep", lambda s: None)

    mod.main([])

    assert captured and captured[0]["atm_iv"] == 0.23
