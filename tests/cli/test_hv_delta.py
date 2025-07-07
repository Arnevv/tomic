from tomic.cli.earnings_info import historical_hv_delta


def test_historical_hv_delta_basic(monkeypatch):
    monkeypatch.setenv("TOMIC_TODAY", "2025-08-01")
    earnings = [
        {"symbol": "AAA", "date": "2025-07-31"},
        {"symbol": "AAA", "date": "2025-04-28"},
    ]
    hv_data = {
        "2025-07-23": {"hv20": 0.165},
        "2025-07-31": {"hv20": 0.187},
        "2025-04-20": {"hv20": 0.200},
        "2025-04-28": {"hv20": 0.230},
    }

    result = historical_hv_delta("AAA", 8, earnings, hv_data)
    assert result is not None
    assert abs(result - 0.1417) < 0.001
