import runpy
import sys
import types
import pytest

# Stub IBAPI modules to avoid import errors
contract_stub = types.ModuleType("ibapi.contract")


class Contract:
    pass


contract_stub.Contract = Contract
sys.modules.setdefault("ibapi.contract", contract_stub)

from tomic.api import market_utils  # noqa: E402


def test_ib_connection_available_false(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError

    monkeypatch.setattr(market_utils.socket, "create_connection", fail)
    assert not market_utils.ib_connection_available("h", 1)


def test_getallmarkets_main_exits(monkeypatch):
    monkeypatch.setattr(
        "tomic.api.getallmarkets.ib_connection_available", lambda: False
    )
    monkeypatch.setattr("tomic.api.getallmarkets.setup_logging", lambda: None)

    exited = []

    def fake_exit(code=0):
        exited.append(code)
        raise SystemExit(code)

    monkeypatch.setattr("tomic.api.getallmarkets.sys.exit", fake_exit)
    monkeypatch.setattr("tomic.api.getallmarkets.sys.argv", ["getallmarkets"])

    with pytest.raises(SystemExit):
        runpy.run_module("tomic.api.getallmarkets", run_name="__main__")

    assert exited == [1]
