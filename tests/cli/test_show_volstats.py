import importlib


def test_show_volstats_main(monkeypatch, tmp_path):
    mod = importlib.import_module("tomic.cli.show_volstats")

    tmp_sum = tmp_path / "sum"
    tmp_hv = tmp_path / "hv"
    tmp_sum.mkdir(); tmp_hv.mkdir()
    (tmp_sum / "ABC.json").write_text('[{"date": "2025-01-01", "atm_iv": 0.3, "iv_rank": 50.0, "iv_percentile": 75.0}]')
    (tmp_hv / "ABC.json").write_text('[{"date": "2025-01-01", "hv20": 0.1, "hv30": 0.2, "hv90": 0.3}]')
    monkeypatch.setattr(mod, "cfg_get", lambda name, default=None: str(tmp_sum) if name=="IV_DAILY_SUMMARY_DIR" else (str(tmp_hv) if name=="HISTORICAL_VOLATILITY_DIR" else default))

    lines = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: lines.append(" ".join(str(x) for x in a)))

    mod.main([])

    assert any("ABC" in line for line in lines)
