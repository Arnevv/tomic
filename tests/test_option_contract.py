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


def test_con_id_roundtrip():
    mod = importlib.import_module("tomic.models")
    info = mod.OptionContract(
        "ABC",
        "20250101",
        100.0,
        "C",
        trading_class="OPTCLS",
        primary_exchange="NASDAQ",
        con_id=42,
    )
    contract = info.to_ib()
    assert contract.conId == 42
    restored = mod.OptionContract.from_ib(contract)
    assert restored.con_id == 42


def test_multiplier_roundtrip():
    mod = importlib.import_module("tomic.models")
    info = mod.OptionContract(
        "ABC",
        "20250101",
        100.0,
        "C",
        multiplier="50",
    )
    contract = info.to_ib()
    assert contract.multiplier == "50"
    restored = mod.OptionContract.from_ib(contract)
    assert restored.multiplier == "50"

