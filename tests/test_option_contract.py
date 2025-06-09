import importlib


def test_to_ib_uses_primary_exchange_and_trading_class():
    mod = importlib.import_module("tomic.models")
    info = mod.OptionContract(
        "ABC",
        "20250101",
        100.0,
        "C",
        trading_class="OPTCLS",
        primary_exchange="NASDAQ",
    )
    contract = info.to_ib()
    assert contract.primaryExchange == "NASDAQ"
    assert contract.tradingClass == "OPTCLS"
