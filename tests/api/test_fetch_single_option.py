import importlib
import sys
import types

# Provide minimal loguru logger stub
loguru_stub = types.ModuleType("loguru")
loguru_stub.logger = types.SimpleNamespace(
    info=lambda *a, **k: None,
    error=lambda *a, **k: None,
    warning=lambda *a, **k: None,
    remove=lambda *a, **k: None,
    add=lambda *a, **k: None,
)
sys.modules.setdefault("loguru", loguru_stub)


def test_security_def_option_parameter_records_trading_class():
    mod = importlib.import_module("tomic.api.fetch_single_option")
    client = mod.StepByStepClient("ABC")
    assert client.option_trading_class is None
    client.securityDefinitionOptionParameter(
        1,
        "SMART",
        123,
        "OPTCLS",
        "100",
        ["20250620"],
        [100.0],
    )
    assert client.option_trading_class == "OPTCLS"
    assert client.option_multiplier == "100"


def test_option_contracts_use_stored_values(monkeypatch):
    mod = importlib.import_module("tomic.api.fetch_single_option")
    client = mod.StepByStepClient("ABC")
    client.option_trading_class = "OPTCLS"
    client.option_multiplier = "100"
    client.expiries = ["20250620"]
    client.strikes = [100.0]
    sent = []

    monkeypatch.setattr(client, "reqContractDetails", lambda reqId, con: sent.append(con), raising=False)
    monkeypatch.setattr(client.contract_received, "clear", lambda: None)
    monkeypatch.setattr(client.contract_received, "wait", lambda t: True)

    symbol = client.symbol
    for expiry in client.expiries:
        for strike in client.strikes:
            for right in ("C", "P"):
                c = mod.Contract()
                c.symbol = symbol
                c.secType = "OPT"
                c.currency = "USD"
                c.exchange = "SMART"
                c.lastTradeDateOrContractMonth = expiry
                c.strike = strike
                c.right = right
                c.tradingClass = client.option_trading_class
                c.multiplier = client.option_multiplier
                req_id = client._next_id()
                client.contract_received.clear()
                client.reqContractDetails(req_id, c)
                client.contract_received.wait(2)

    assert len(sent) == 2
    assert all(c.tradingClass == "OPTCLS" for c in sent)
    assert all(c.multiplier == "100" for c in sent)
