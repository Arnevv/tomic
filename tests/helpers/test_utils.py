import importlib

from tomic import utils


def test_filter_future_expiries_respects_today(monkeypatch):
    monkeypatch.setenv("TOMIC_TODAY", "2025-06-08")
    importlib.reload(utils)

    expiries = ["20240614", "20250606", "20250620", "20250627"]
    result = utils.filter_future_expiries(expiries)
    assert result == ["20250620", "20250627"]


def test_get_option_mid_price_bid_ask():
    option = {"bid": 1.0, "ask": 1.2, "close": 0.5}
    assert utils.get_option_mid_price(option) == 1.1


def test_get_option_mid_price_fallback_close():
    option = {"bid": None, "ask": None, "close": 0.8}
    assert utils.get_option_mid_price(option) == 0.8


