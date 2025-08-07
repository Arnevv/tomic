import csv

import tomic.strategy_candidates as sc
from tomic.api.market_export import load_exported_chain


def test_load_exported_chain_normalizes_open_interest(tmp_path, monkeypatch):
    csv_path = tmp_path / "chain.csv"
    with csv_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Expiry",
            "Type",
            "Strike",
            "OpenInterest",
            "Bid",
            "Ask",
            "Delta",
            "Model",
            "Mid",
            "Edge",
        ])
        writer.writerow([
            "20250101",
            "C",
            "100",
            "42",
            "1",
            "2",
            "0.5",
            "1",
            "1.5",
            "0",
        ])
    rows = load_exported_chain(str(csv_path))
    assert rows[0]["open_interest"] == 42.0
    leg = rows[0]
    leg.update({"position": -1})

    def fake_cfg_get(key, default=None):
        if key == "MIN_OPTION_OPEN_INTEREST":
            return 10
        if key == "MIN_OPTION_VOLUME":
            return 0
        return default

    monkeypatch.setattr(sc, "cfg_get", fake_cfg_get)
    monkeypatch.setattr(sc, "calculate_margin", lambda *a, **k: 1)
    metrics, reasons = sc._metrics("test", [leg])
    assert metrics is not None
    assert "onvoldoende volume/open interest" not in reasons
