import math
from datetime import datetime, timedelta

import importlib


def test_calculate_hv_constant():
    from tomic.analysis.metrics import historical_volatility

    prices = [100 * 1.01 ** i for i in range(260)]
    hv = historical_volatility(prices, window=252)
    assert hv is not None
    assert math.isclose(hv, 0.0, abs_tol=1e-12)


def test_run_backfill_hv(monkeypatch, tmp_path):
    module = importlib.import_module("tomic.scripts.backfill_hv")
    monkeypatch.setattr(
        "tomic.services.marketdata.volatility_service.cfg_get",
        lambda name, default=None: ["AAA"] if name == "DEFAULT_SYMBOLS" else default,
    )

    start_dt = datetime(2024, 10, 1)
    closes = [100 * 1.01 ** i for i in range(280)]

    def fake_history(symbol):
        for i in range(280):
            yield {
                "date": (start_dt + timedelta(days=i)).strftime("%Y-%m-%d"),
                "close": closes[i],
            }

    monkeypatch.setattr(
        "tomic.services.marketdata.volatility_service.load_price_history",
        lambda symbol: list(fake_history(symbol)),
    )
    monkeypatch.setattr(
        "tomic.services.marketdata.volatility_service.today",
        lambda: datetime(2025, 7, 7),
    )

    from tomic.services.marketdata.storage_service import (
        HistoricalVolatilityStorageService,
    )

    storage = HistoricalVolatilityStorageService(base_dir=tmp_path)
    storage.append(
        "AAA",
        [
            {
                "date": "2025-07-03",
                "hv20": 0.0,
                "hv30": 0.0,
                "hv90": 0.0,
                "hv252": 0.0,
            }
        ],
    )
    monkeypatch.setattr(
        "tomic.services.marketdata.volatility_service.HistoricalVolatilityStorageService",
        lambda: storage,
    )

    module.run_backfill_hv()

    output = tmp_path / "AAA.json"
    assert output.exists()
    data = importlib.import_module("tomic.journal.utils").load_json(output)
    assert len(data) == 28
    new_records = [rec for rec in data if rec["date"] != "2025-07-03"]
    assert len(new_records) == 27
    assert all(rec["hv252"] == 0.0 for rec in new_records)
