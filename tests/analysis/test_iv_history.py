import importlib
import importlib
from datetime import date


def _sample_data():
    data = []
    expiries = ["20240105", "20240202", "20240302"]
    for exp in expiries:
        data.extend(
            [
                {"expiry": exp, "strike": 100, "right": "call", "iv": 0.2, "delta": 0.5},
                {"expiry": exp, "strike": 100, "right": "put", "iv": 0.21, "delta": -0.5},
                {"expiry": exp, "strike": 110, "right": "CALL", "iv": 0.18, "delta": 0.25},
                {"expiry": exp, "strike": 110, "right": "PUT", "iv": 0.22, "delta": -0.75},
                {"expiry": exp, "strike": 90, "right": "c", "iv": 0.19, "delta": 0.75},
                {"expiry": exp, "strike": 90, "right": "p", "iv": 0.23, "delta": -0.25},
            ]
        )
    return data, expiries


def test_extract_iv_points(monkeypatch):
    mod = importlib.import_module("tomic.analysis.iv_history")

    monkeypatch.setattr(mod, "cfg_get", lambda name, default=None: [0, 30, 60] if name == "IV_EXPIRY_LOOKAHEAD_DAYS" else [0.25, 0.5])

    data, expiries = _sample_data()
    result = mod.extract_iv_points(data, expiries, spot_price=100.0, obs_date="2024-01-01")
    assert len(result) == 18
    assert any(r["strike"] == 110 and r["right"] == "CALL" for r in result)
    assert any(r["strike"] == 90 and r["right"] == "PUT" for r in result)


def test_store_iv_history(monkeypatch):
    mod = importlib.import_module("tomic.analysis.iv_history")

    captured = []
    monkeypatch.setattr(mod, "update_json_file", lambda f, rec, keys: captured.append((f, rec, keys)))
    monkeypatch.setattr(mod, "cfg_get", lambda name, default=None: "tmp" if name == "IV_HISTORY_DIR" else [0, 30, 60] if name == "IV_EXPIRY_LOOKAHEAD_DAYS" else [0.25, 0.5])

    data, expiries = _sample_data()
    mod.store_iv_history("XYZ", data, expiries, spot_price=100.0, obs_date="2024-01-01")
    assert len(captured) == 18
    file, rec, keys = captured[0]
    assert "XYZ.json" in str(file)
    assert set(keys) == {"date", "expiry", "right", "strike"}
