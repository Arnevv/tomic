import importlib
from tomic.journal.utils import save_json


def test_show_volsnapshot_table_output(monkeypatch, capsys, tmp_path):
    mod = importlib.import_module("tomic.cli.show_volsnapshot")
    sum_dir = tmp_path / "sum"
    hv_dir = tmp_path / "hv"
    sum_dir.mkdir(); hv_dir.mkdir()
    save_json([
        {"date": "2024-01-01", "atm_iv": 0.5, "iv_rank": 10.0, "iv_percentile": 20.0}
    ], sum_dir / "AAA.json")
    save_json([
        {"date": "2024-01-01", "atm_iv": 0.6, "iv_rank": 11.0, "iv_percentile": 21.0}
    ], sum_dir / "BBB.json")
    save_json([
        {"date": "2024-01-01", "hv20": 0.4, "hv30": 0.3, "hv90": 0.2}
    ], hv_dir / "AAA.json")
    save_json([
        {"date": "2024-01-01", "hv20": 0.5, "hv30": 0.4, "hv90": 0.3}
    ], hv_dir / "BBB.json")
    monkeypatch.setattr(
        mod,
        "cfg_get",
        lambda name, default=None: str(sum_dir)
        if name == "IV_DAILY_SUMMARY_DIR"
        else (str(hv_dir) if name == "HISTORICAL_VOLATILITY_DIR" else default),
    )
    monkeypatch.setattr(mod, "setup_logging", lambda: None)

    mod.main(["2024-01-01"])

    out = capsys.readouterr().out
    assert "AAA" in out
    assert "BBB" in out
    assert "symbol" in out
