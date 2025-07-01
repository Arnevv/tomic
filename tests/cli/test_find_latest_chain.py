import importlib
import time
from pathlib import Path


def _patch_export_dir(mod, path: Path, monkeypatch):
    monkeypatch.setattr(
        mod.cfg,
        "get",
        lambda name, default=None: str(path) if name == "EXPORT_DIR" else default,
    )


def test_find_latest_chain_found(tmp_path, monkeypatch):
    mod = importlib.import_module("tomic.cli.controlpanel")
    _patch_export_dir(mod, tmp_path, monkeypatch)

    d1 = tmp_path / "20240101"
    d2 = tmp_path / "20240102"
    d1.mkdir()
    d2.mkdir()

    f1 = d1 / "option_chain_XYZ_111.csv"
    f1.write_text("data1")
    time.sleep(0.01)
    f2 = d2 / "option_chain_XYZ_222.csv"
    f2.write_text("data2")

    assert mod.find_latest_chain("XYZ") == f2


def test_find_latest_chain_none(tmp_path, monkeypatch):
    mod = importlib.import_module("tomic.cli.controlpanel")
    _patch_export_dir(mod, tmp_path, monkeypatch)

    assert mod.find_latest_chain("AAA") is None


def test_find_latest_chain_no_base(monkeypatch, tmp_path):
    mod = importlib.import_module("tomic.cli.controlpanel")
    nonexist = tmp_path / "missing"
    _patch_export_dir(mod, nonexist, monkeypatch)

    assert mod.find_latest_chain("XYZ") is None


def test_find_latest_chain_case_insensitive(tmp_path, monkeypatch):
    mod = importlib.import_module("tomic.cli.controlpanel")
    _patch_export_dir(mod, tmp_path, monkeypatch)

    d = tmp_path / "d"
    d.mkdir()
    f = d / "option_chain_XYZ_123.csv"
    f.write_text("data")

    assert mod.find_latest_chain("xyz") == f

