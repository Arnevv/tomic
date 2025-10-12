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

    orig_load = sc.load_criteria

    def fake_load():
        cfg = orig_load()
        cfg.market_data.min_option_open_interest = 10
        cfg.market_data.min_option_volume = 0
        return cfg

    monkeypatch.setattr(sc, "load_criteria", fake_load)
    monkeypatch.setattr(sc, "calculate_margin", lambda *a, **k: 1)
    metrics, reasons = sc._metrics("test", [leg])
    assert metrics is not None
    assert "onvoldoende volume/open interest" not in [r.message for r in reasons]
