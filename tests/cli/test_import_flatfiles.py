import importlib
import gzip
import json


def _sample_options():
    return [
        {
            "underlying_ticker": "SPY",
            "expiration_date": "2024-07-19",
            "strike_price": 100.0,
            "delta": 0.5,
            "implied_volatility": 0.2,
            "option_type": "call",
        },
        {
            "underlying_ticker": "SPY",
            "expiration_date": "2024-07-19",
            "strike_price": 105.0,
            "delta": 0.25,
            "implied_volatility": 0.21,
            "option_type": "call",
        },
        {
            "underlying_ticker": "SPY",
            "expiration_date": "2024-07-19",
            "strike_price": 95.0,
            "delta": -0.25,
            "implied_volatility": 0.24,
            "option_type": "put",
        },
        {
            "underlying_ticker": "SPY",
            "expiration_date": "2024-08-16",
            "strike_price": 100.0,
            "delta": 0.5,
            "implied_volatility": 0.19,
            "option_type": "call",
        },
        {
            "underlying_ticker": "SPY",
            "expiration_date": "2024-09-20",
            "strike_price": 100.0,
            "delta": 0.5,
            "implied_volatility": 0.18,
            "option_type": "call",
        },
    ]


def test_compute_metrics(monkeypatch):
    mod = importlib.import_module("tomic.cli.import_flatfiles")

    monkeypatch.setattr(mod, "_get_close_for_date", lambda s, d: 100.0)
    monkeypatch.setattr(mod, "_get_closes", lambda s: [1.0] * 60)
    monkeypatch.setattr(mod, "_rolling_hv", lambda closes, window: [10.0, 50.0])

    metrics = mod._compute_metrics_for_symbol(_sample_options(), "SPY", "2024-06-24")

    assert metrics["atm_iv"] == 0.2
    assert metrics["skew"] == 3.0
    assert metrics["term_m1_m2"] == 1.0
    assert metrics["term_m1_m3"] == 2.0
    assert metrics["iv_rank (HV)"] == 25.0
    assert metrics["iv_percentile (HV)"] == 50.0


def test_import_flatfiles_main(monkeypatch, tmp_path):
    mod = importlib.import_module("tomic.cli.import_flatfiles")

    flat_dir = tmp_path / "flat"
    flat_dir.mkdir()
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    path = flat_dir / "options_2024-06-24.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for rec in _sample_options():
            fh.write(json.dumps(rec) + "\n")

    monkeypatch.setattr(
        mod,
        "cfg_get",
        lambda name, default=None: ["SPY"] if name == "DEFAULT_SYMBOLS" else str(flat_dir) if name == "FLATFILE_DIR" else str(out_dir) if name == "IV_DAILY_SUMMARY_DIR" else default,
    )
    monkeypatch.setattr(mod, "_get_close_for_date", lambda s, d: 100.0)
    monkeypatch.setattr(mod, "_get_closes", lambda s: [1.0] * 60)
    monkeypatch.setattr(mod, "_rolling_hv", lambda closes, window: [10.0, 50.0])

    captured = []
    monkeypatch.setattr(mod, "update_json_file", lambda f, rec, keys: captured.append((f, rec)))

    mod.main(["--dir", str(flat_dir)])

    assert captured
    file, record = captured[0]
    assert record["date"] == "2024-06-24"
    assert file.name == "SPY.json"
    assert not path.exists()

