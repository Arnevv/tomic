import importlib


def test_first_expiry_min_dte(monkeypatch):
    monkeypatch.setenv("TOMIC_TODAY", "2024-06-01")
    mod = importlib.import_module("tomic.api.market_client")
    monkeypatch.setattr(mod, "cfg_get", lambda n, d=None: 15 if n == "FIRST_EXPIRY_MIN_DTE" else d)

    client = mod.OptionChainClient("ABC")
    client.spot_price = 100.0
    expiries = ["20240614", "20240621", "20240719"]
    client.securityDefinitionOptionParameter(1, "SMART", 1, "TC", "100", expiries, [100.0])

    assert client.expiries and client.expiries[0] == "20240621"
