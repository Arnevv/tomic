import runpy
import sys
import types
import builtins
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


def test_getonemarket_main_exits(monkeypatch):
    monkeypatch.setattr(
        "tomic.api.getonemarket.ib_connection_available",
        lambda: False,
    )
    monkeypatch.setattr("tomic.api.getonemarket.setup_logging", lambda: None)

    exited: list[int] = []

    def fake_exit(code: int = 0) -> None:
        exited.append(code)
        raise SystemExit(code)

    monkeypatch.setattr("tomic.api.getonemarket.sys.exit", fake_exit)
    monkeypatch.setattr(
        "tomic.api.getonemarket.sys.argv",
        ["getonemarket", "AAPL"],
    )

    with pytest.raises(SystemExit):
        runpy.run_module("tomic.api.getonemarket", run_name="__main__")

    assert exited == [1]


def test_check_ib_connection(monkeypatch):
    from tomic.cli import controlpanel

    output: list[str] = []
    monkeypatch.setattr(controlpanel, "ib_api_available", lambda: True)
    monkeypatch.setattr(
        builtins, "print", lambda *a, **k: output.append(" ".join(str(x) for x in a))
    )
    controlpanel.check_ib_connection()
    assert any("✅" in line for line in output)

    output.clear()
    monkeypatch.setattr(controlpanel, "ib_api_available", lambda: False)
    controlpanel.check_ib_connection()
    assert any("❌" in line for line in output)
