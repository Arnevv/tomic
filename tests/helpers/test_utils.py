import importlib
import json

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


def test_latest_atr(monkeypatch, tmp_path):
    data = [
        {"date": "2024-01-01", "close": 100.0, "atr": None},
        {"date": "2024-01-02", "close": 101.0, "atr": 1.5},
        {"date": "2024-01-03", "close": 102.0, "atr": None},
    ]
    path = tmp_path / "AAA.json"
    path.write_text(json.dumps(data))

    monkeypatch.setattr(
        utils, "cfg_get", lambda name, default=None: str(tmp_path)
        if name == "PRICE_HISTORY_DIR"
        else default,
    )
    importlib.reload(utils)

    assert utils.latest_atr("AAA") == 1.5


def test_latest_atr_none(monkeypatch, tmp_path):
    path = tmp_path / "AAA.json"
    path.write_text("[]")

    monkeypatch.setattr(
        utils, "cfg_get", lambda name, default=None: str(tmp_path)
        if name == "PRICE_HISTORY_DIR"
        else default,
    )
    importlib.reload(utils)

    assert utils.latest_atr("AAA") is None


def test_normalize_leg(monkeypatch):
    leg = {
        "Delta": "0.5",
        "mid": "1.2",
        "strike": "100",
        "gamma": "0.1",
        "bad": "x",
    }
    out = utils.normalize_leg(leg)
    assert out["delta"] == 0.5
    assert out["mid"] == 1.2
    assert out["strike"] == 100.0
    assert out["gamma"] == 0.1
    assert out["bad"] == "x"
    assert "Delta" not in out

    leg2 = {"delta": "abc"}
    out2 = utils.normalize_leg(leg2)
    assert out2["delta"] is None


def test_prompt_user_for_price_accept(monkeypatch):
    inputs = iter(["y", "0.25"])
    monkeypatch.setattr("builtins.input", lambda *a: next(inputs))
    price = utils.prompt_user_for_price(143, "2025-07-25", "C", 1)
    assert price == 0.25


def test_prompt_user_for_price_decline(monkeypatch):
    inputs = iter(["n"])
    monkeypatch.setattr("builtins.input", lambda *a: next(inputs))
    price = utils.prompt_user_for_price(143, "2025-07-25", "C", 1)
    assert price is None


def test_get_option_mid_price_nan_bid_ask():
    option = {"bid": "NaN", "ask": "nan", "close": None}
    assert utils.get_option_mid_price(option) is None


def test_get_option_mid_price_nan_close():
    option = {"bid": None, "ask": None, "close": "NaN"}
    assert utils.get_option_mid_price(option) is None


