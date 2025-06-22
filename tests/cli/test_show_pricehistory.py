import importlib
from tomic.journal.utils import save_json


def test_show_pricehistory(monkeypatch, capsys, tmp_path):
    mod = importlib.import_module("tomic.cli.show_pricehistory")

    tmp = tmp_path / "spot"
    tmp.mkdir()
    file = tmp / "AAA.json"
    save_json([
        {"date": "2024-01-01", "close": 1.23, "volume": 100, "atr": None},
        {"date": "2024-01-02", "close": 1.25, "volume": 120, "atr": None},
    ], file)
    monkeypatch.setattr(mod, "cfg_get", lambda name, default=None: str(tmp) if name == "PRICE_HISTORY_DIR" else default)
    monkeypatch.setattr(mod, "setup_logging", lambda: None)

    mod.main(["AAA"])

    out = capsys.readouterr().out
    assert "2024-01-01" in out
    assert "1.23" in out
    assert "2024-01-02" in out
