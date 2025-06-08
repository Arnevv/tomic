import importlib

from tomic import utils


def test_filter_future_expiries_respects_today(monkeypatch):
    monkeypatch.setenv("TOMIC_TODAY", "2025-06-08")
    importlib.reload(utils)

    expiries = ["20240614", "20250606", "20250620", "20250627"]
    result = utils.filter_future_expiries(expiries)
    assert result == ["20250620", "20250627"]


