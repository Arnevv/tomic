import importlib
import math
from datetime import datetime, timedelta
from pathlib import Path


def test_calculate_hv_constant():
    mod = importlib.import_module("tomic.scripts.backfill_hv")
    prices = [100 * 1.01 ** i for i in range(260)]
    hv = mod._calculate_hv(prices)
    assert math.isclose(hv[-1]["hv252"], 0.0, abs_tol=1e-12)


def test_run_backfill_hv(monkeypatch):
    mod = importlib.import_module("tomic.scripts.backfill_hv")
    monkeypatch.setenv("TOMIC_TODAY", "2025-07-07")
    importlib.reload(mod)

    # configuration
    monkeypatch.setattr(mod, "cfg_get", lambda name, default=None: ["AAA"] if name == "DEFAULT_SYMBOLS" else default)

    start_dt = datetime(2024, 10, 1)
    closes = [100 * 1.01 ** i for i in range(280)]
    def _mock_price(symbol):
        recs = []
        for i in range(280):
            d = (start_dt + timedelta(days=i)).strftime("%Y-%m-%d")
            recs.append((d, closes[i]))
        return recs
    monkeypatch.setattr(mod, "_load_price_data", _mock_price)

    hv_existing = [{"date": "2025-07-03", "hv20": 0.0, "hv30": 0.0, "hv90": 0.0, "hv252": 0.0}]
    monkeypatch.setattr(mod, "_load_existing_hv", lambda symbol: (hv_existing, Path("hv.json")))

    saved: list[dict] = []
    monkeypatch.setattr(mod, "_save_hv", lambda s, data: saved.extend(data))

    mod.run_backfill_hv()
    assert len(saved) == 4
    assert all(rec["hv252"] == 0.0 for rec in saved)
