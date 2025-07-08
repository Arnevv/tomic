import importlib


def test_compute_volstats_polygon_intraday(monkeypatch):
    mod = importlib.import_module("tomic.cli.compute_volstats_polygon")

    monkeypatch.setattr(mod, "cfg_get", lambda name, default=None: ["ABC"] if name == "DEFAULT_SYMBOLS" else default)

    # base closes do not include intraday price
    monkeypatch.setattr(mod, "_get_closes", lambda sym: [1.0] * 30)
    monkeypatch.setattr(mod, "_load_latest_close", lambda sym: (2.0, "2024-01-02"))

    hv_inputs = []

    def hv_stub(closes, *, window, trading_days=252):
        hv_inputs.append(closes[-1])
        return closes[-1]

    monkeypatch.setattr(mod, "historical_volatility", hv_stub)
    monkeypatch.setattr(mod, "fetch_polygon_iv30d", lambda sym: {"atm_iv": 0.1, "term_m1_m2": 0.0, "term_m1_m3": 0.0, "skew": 0.0})
    monkeypatch.setattr(mod, "sleep", lambda s: None)

    records = []
    monkeypatch.setattr(mod, "update_json_file", lambda f, r, k: records.append(r))

    mod.main([])

    hv_record = next(r for r in records if "hv20" in r)
    iv_record = next(r for r in records if "atm_iv" in r)

    assert hv_record["date"] == "2024-01-02"
    assert iv_record["date"] == "2024-01-02"
    assert hv_inputs and hv_inputs[-1] == 2.0
    assert abs(hv_record["hv20"] - 0.02) < 1e-9
