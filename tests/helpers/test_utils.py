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
    assert utils.get_option_mid_price(option) == (1.1, False)


def test_get_option_mid_price_fallback_close():
    option = {"bid": None, "ask": None, "close": 0.8}
    assert utils.get_option_mid_price(option) == (0.8, True)


def test_load_price_history(monkeypatch, tmp_path):
    data = [
        {"date": "2024-01-02", "close": 101.0},
        {"date": "2024-01-01", "close": 100.0},
    ]
    path = tmp_path / "AAA.json"
    path.write_text(json.dumps(data))

    importlib.reload(utils)
    monkeypatch.setattr(
        utils,
        "cfg_get",
        lambda name, default=None: str(tmp_path)
        if name == "PRICE_HISTORY_DIR"
        else default,
    )

    records = utils.load_price_history("AAA")
    assert [r.get("date") for r in records] == ["2024-01-01", "2024-01-02"]


def test_latest_atr(monkeypatch, tmp_path):
    data = [
        {"date": "2024-01-01", "close": 100.0, "atr": None},
        {"date": "2024-01-02", "close": 101.0, "atr": 1.5},
        {"date": "2024-01-03", "close": 102.0, "atr": None},
    ]
    path = tmp_path / "AAA.json"
    path.write_text(json.dumps(data))

    importlib.reload(utils)
    monkeypatch.setattr(
        utils, "cfg_get", lambda name, default=None: str(tmp_path)
        if name == "PRICE_HISTORY_DIR"
        else default,
    )

    assert utils.latest_atr("AAA") == 1.5


def test_latest_atr_none(monkeypatch, tmp_path):
    path = tmp_path / "AAA.json"
    path.write_text("[]")

    importlib.reload(utils)
    monkeypatch.setattr(
        utils, "cfg_get", lambda name, default=None: str(tmp_path)
        if name == "PRICE_HISTORY_DIR"
        else default,
    )

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


def test_normalize_leg_camel_case():
    leg = {"OpenInterest": "415"}
    out = utils.normalize_leg(leg)
    assert out == {"open_interest": 415.0}


def test_normalize_leg_openinterest():
    input_leg = {"openinterest": "1289"}
    result = utils.normalize_leg(input_leg)
    assert result["open_interest"] == 1289


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
    assert utils.get_option_mid_price(option) == (None, False)


def test_get_option_mid_price_nan_close():
    option = {"bid": None, "ask": None, "close": "NaN"}
    assert utils.get_option_mid_price(option) == (None, False)


def test_get_leg_right_prefers_right():
    leg = {"right": "P", "type": "C"}
    assert utils.get_leg_right(leg) == "put"


def test_get_leg_right_fallback_type():
    leg = {"type": "C"}
    assert utils.get_leg_right(leg) == "call"


def test_get_leg_qty_prefers_qty():
    leg = {"qty": 2, "quantity": 4, "position": 5}
    assert utils.get_leg_qty(leg) == 2.0


def test_get_leg_qty_fallback_quantity():
    leg = {"quantity": "3"}
    assert utils.get_leg_qty(leg) == 3.0


def test_get_leg_qty_fallback_position():
    leg = {"position": -6}
    assert utils.get_leg_qty(leg) == 6.0


def test_get_leg_qty_default_one():
    assert utils.get_leg_qty({}) == 1.0


